"""Run the real pilot preflight CLI without source networking; never start a stack."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

from tools.pilot_deployment.doctor import SECRET_KEYS, read_dotenv

root = Path(sys.argv[1]).resolve()
image_project = sys.argv[2]
commit = subprocess.check_output(
    ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
).strip()
python_image = next(
    line.split("=", 1)[1].strip("\"'")
    for line in (root / "infra/locks/images.env").read_text().splitlines()
    if line.startswith("PYTHON_IMAGE=")
)

with tempfile.TemporaryDirectory(prefix="survey-pilot-preflight-") as temporary:
    proof = Path(temporary)
    values = read_dotenv(root / ".env.local")
    for key in SECRET_KEYS:
        values[key] = secrets.token_hex(32)
    for key in values:
        if any(
            word in key
            for word in (
                "SECRET",
                "PASSWORD",
                "TOKEN",
                "ENCRYPTION_KEY",
                "ACCESS_KEY",
                "API_KEY",
            )
        ):
            values[key] = secrets.token_hex(32)
    values.update(
        {
            "LEONAID_ENV": "production",
            "LEONAID_DEPLOYMENT_STAGE": "production",
            "LEONAID_COMPOSE_PROJECT": f"leonaid-production-test-preflight-{os.getpid()}",
            "LEONAID_SERVICE_VERSION": "0.1.0",
            "LEONAID_RELEASE_COMMIT": commit,
            "LEONAID_PUBLIC_DOMAIN": "portal.leonaid.org",
            "LEONAID_PUBLIC_BASE_URL": "https://portal.leonaid.org",
            "LEONAID_ALLOWED_ORIGINS": "https://portal.leonaid.org",
            "TWENTY_PUBLIC_DOMAIN": "crm.leonaid.org",
            "TWENTY_PUBLIC_BASE_URL": "https://crm.leonaid.org",
            "CADDY_ACME_EMAIL": "operations@leonaid.org",
            "RUSTFS_BUCKET": "leonaid-production-preflight",
            "MAIL_HEALTH_URL": "https://portal.leonaid.org/_health",
            "MAIL_SMTP_HOST": "smtp.leonaid.org",
            "MAIL_SMTP_PORT": "587",
            "MAIL_FROM": "noreply@leonaid.org",
            "MAIL_ENVELOPE_FROM": "bounces@leonaid.org",
            "MAIL_REPLY_TO": "support@leonaid.org",
            "MAIL_SMTP_MODE": "starttls",
            "MAIL_SMTP_USERNAME": "synthetic-preflight",
            "MAIL_SMTP_PASSWORD": secrets.token_hex(32),
            "RESTIC_REPOSITORY": "s3:https://backup.leonaid.org/synthetic-preflight",
            "LEONAID_BACKUP_MANIFEST_PATH": "/proof/backup-manifest.json",
            "LEONAID_MONITORED_DISK_PATH": "/proof",
            "LEONAID_ALERT_WEBHOOK_URL_FILE": "/proof/webhook-url",
        }
    )
    for service, key in {
        "api": "CORE",
        "web": "WEB",
        "pwa": "PWA",
        "public": "PUBLIC",
        "survey-validator": "SURVEY_VALIDATOR",
    }.items():
        values[f"LEONAID_{key}_IMAGE"] = subprocess.check_output(
            [
                "docker",
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                f"{image_project}-{service}",
            ],
            text=True,
        ).strip()
    env_file = proof / "production.env"
    env_file.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    env_file.chmod(0o600)
    (proof / "webhook-url").write_text(
        "https://alerts.leonaid.org/synthetic-preflight\n"
    )
    (proof / "webhook-url").chmod(0o600)
    overlay = proof / "overlay.yml"
    overlay.write_text(
        'services:\n  proxy:\n    ports: !override\n      - "127.0.0.1:19080:80"\n      - "127.0.0.1:19443:443"\n'
    )
    compose = subprocess.check_output(
        [
            "docker",
            "compose",
            "--project-name",
            values["LEONAID_COMPOSE_PROJECT"],
            "--env-file",
            str(env_file),
            "-f",
            str(root / "infra/compose/compose.yml"),
            "-f",
            str(root / "infra/pilot/compose.yml"),
            "-f",
            str(overlay),
            "config",
            "--format",
            "json",
        ],
        text=True,
    )
    config = json.loads(compose)
    assert "build" not in config["services"]["survey-validator"]
    assert (
        config["services"]["survey-validator"]["image"]
        == values["LEONAID_SURVEY_VALIDATOR_IMAGE"]
    )
    (proof / "compose.json").write_text(compose)
    backup = {
        "schemaVersion": 1,
        "sourceProject": values["LEONAID_COMPOSE_PROJECT"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "files": {
            name: {"sha256": "a" * 64, "size": 1}
            for name in (
                "core.dump",
                "twenty.dump",
                "twenty-storage.tar",
                "rustfs-data.tar",
            )
        },
    }
    (proof / "backup-manifest.json").write_text(json.dumps(backup))
    decisions = (root / "specs/leonaid-pilot/DECISIONS.md").read_text()
    accepted = []
    for line in decisions.splitlines():
        if line.startswith("| PILOT-"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            cells[6:9] = [
                "EVID-TEST-" + cells[0].removeprefix("PILOT-"),
                "accepted",
                "small_business"
                if cells[0] == "PILOT-TAX-001"
                else "not_required"
                if cells[0] == "PILOT-INV-002"
                else "confirmed",
            ]
            line = "| " + " | ".join(cells) + " |"
        accepted.append(line)
    (proof / "accepted.md").write_text("\n".join(accepted) + "\n")
    (proof / "open.md").write_text(decisions)

    def run(gate="pilot-restore", register="accepted.md", expected=0):
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "-e",
                "PYTHONPATH=/workspace",
                "-v",
                f"{root}:/workspace:ro",
                "-v",
                f"{proof}:/proof:ro",
                "-v",
                f"{proof / register}:/workspace/specs/leonaid-pilot/DECISIONS.md:ro",
                "-w",
                "/workspace",
                python_image,
                "python",
                "tools/pilot_deployment/doctor.py",
                "/workspace",
                "--env-file",
                "/proof/production.env",
                "--compose-config",
                "/proof/compose.json",
                "--backup-manifest",
                "/proof/backup-manifest.json",
                "--expected-release-commit",
                commit,
                "--isolated-test-mode",
                "--gate",
                gate,
                "--json",
                "--disk-path",
                "/proof",
                "--minimum-free-bytes",
                "1048576",
                "--timeout-seconds",
                "1",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == expected, (
            gate,
            result.returncode,
            result.stdout,
            result.stderr,
        )
        return json.loads(result.stdout)

    result = run()
    assert result["status"] == "ready"
    assert all(
        result["checks"][key] == "not_checked_restore"
        for key in ("dns", "tls", "dependencies", "time")
    )
    assert run(register="open.md", expected=2)["status"] == "blocked"
    assert run(gate="pilot-deploy", expected=1)["error"].startswith("dns_failed:")
    stale = {
        **backup,
        "createdAt": (datetime.now(timezone.utc) - timedelta(hours=27)).isoformat(),
    }
    (proof / "backup-manifest.json").write_text(json.dumps(stale))
    assert run(expected=1)["error"] == "backup_too_old"
    (proof / "backup-manifest.json").write_text(json.dumps(backup))
    config["services"]["survey-validator"]["image"] = "survey-validator:latest"
    (proof / "compose.json").write_text(json.dumps(config))
    assert "digest-gepinnt" in run(expected=1)["error"]
    config["services"]["survey-validator"]["image"] = values[
        "LEONAID_SURVEY_VALIDATOR_IMAGE"
    ]
    (proof / "compose.json").write_text(json.dumps(config))

    def manifest(command, *arguments, expected=0):
        outcome = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "-e",
                "PYTHONPATH=/workspace",
                "-v",
                f"{root}:/workspace:ro",
                "-v",
                f"{proof}:/proof",
                "-w",
                "/workspace",
                python_image,
                "python",
                "tools/pilot_release/manifest.py",
                command,
                "--root",
                "/workspace",
                *arguments,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert outcome.returncode == expected, (outcome.stdout, outcome.stderr)

    manifest(
        "create",
        "--release-id",
        "surveys-preflight",
        "--version",
        "0.1.0",
        "--git-commit",
        commit,
        "--deployment-mode",
        "test",
        "--compose-config",
        "/proof/compose.json",
        "--output",
        "/proof/release.json",
    )
    manifest(
        "verify",
        "--manifest",
        "/proof/release.json",
        "--expected-commit",
        commit,
        "--compose-config",
        "/proof/compose.json",
    )
    release = json.loads((proof / "release.json").read_text())
    assert (
        release["images"]["survey-validator"]
        == values["LEONAID_SURVEY_VALIDATOR_IMAGE"]
    )
    config["services"]["survey-validator"]["image"] = values["LEONAID_CORE_IMAGE"]
    (proof / "compose.json").write_text(json.dumps(config))
    manifest(
        "verify",
        "--manifest",
        "/proof/release.json",
        "--expected-commit",
        commit,
        "--compose-config",
        "/proof/compose.json",
        expected=1,
    )
    del release["images"]["survey-validator"]
    (proof / "release.json").write_text(json.dumps(release))
    manifest("verify", "--manifest", "/proof/release.json", expected=1)

    # Run the exact validator image bound by the production overlay. The source
    # stack need not exist; this one container has no network or published ports.
    container = subprocess.check_output(
        [
            "docker",
            "run",
            "--detach",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--name",
            values["LEONAID_COMPOSE_PROJECT"] + "-validator",
            values["LEONAID_SURVEY_VALIDATOR_IMAGE"],
        ],
        text=True,
    ).strip()
    try:
        subprocess.run(
            [
                "docker",
                "exec",
                container,
                "bun",
                "-e",
                """
let ready = false;
for (let attempt=0; attempt<100; attempt++) {
  try {
    const health=await (await fetch("http://127.0.0.1:8080/health")).json();
    if (health.status==="ok" && health.renderer==="3.0.3") { ready=true; break; }
  } catch {}
  await Bun.sleep(100);
}
if (!ready) throw new Error("validator readiness failed");
for (const [answers, valid] of [[{}, false], [{answer:"synthetic"}, true]]) {
  const response=await fetch("http://127.0.0.1:8080/validate", {
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({profile:"initial-v1",definition:{pages:[{name:"main",
      elements:[{name:"answer",type:"text",isRequired:true}]}]},answers})});
  const result=await response.json();
  if (response.status!==200 || result.completeValid!==valid || result.renderer!=="3.0.3")
    throw new Error("validator result mismatch");
}
console.log("PASS: pinned validator required-answer semantics without source networking");
""",
            ],
            check=True,
            timeout=20,
        )
        inspected = json.loads(
            subprocess.check_output(["docker", "inspect", container], text=True)
        )[0]
        assert inspected["Image"] == values["LEONAID_SURVEY_VALIDATOR_IMAGE"]
        assert inspected["HostConfig"]["NetworkMode"] == "none"
        assert not inspected["HostConfig"]["PortBindings"]
    finally:
        subprocess.run(
            ["docker", "rm", "--force", container],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    artifact = root / ".artifacts/surveys-pilot-preflight"
    artifact.mkdir(parents=True, exist_ok=True)
    (artifact / "proof.json").write_text(
        json.dumps(
            {
                "syntheticOnly": True,
                "realDoctorCliWithNetworkNone": True,
                "sourceUnreachableDoesNotBlockRestorePreflight": True,
                "liveChecksExplicitlyNotClaimed": True,
                "deploymentStillRequiresLiveSource": True,
                "openDecisionsStillBlockRestore": True,
                "staleBackupStillBlocksRestore": True,
                "validatorHasNoProductionBuildAndUsesImmutableImage": True,
                "mutableValidatorImageRejected": True,
                "releaseManifestBindsValidatorImage": True,
                "changedOrMissingValidatorImageRejected": True,
                "exactPinnedValidatorRunsWithNetworkNone": True,
                "requiredAnswerSemanticsVerified": True,
                "limitations": [
                    "Synthetic backup metadata checks preflight only; actual pilot wrapper and Restic restore remain separate acceptance"
                ],
            },
            indent=2,
        )
        + "\n"
    )
    print(
        "PASS: real network-disabled restore preflight, deployment/decision/backup negatives and immutable validator contract"
    )
