"""Parse real invitation response exports and retain private log-scan markers."""

import asyncio
import csv
import io
import json
from pathlib import Path
from zipfile import ZipFile

import httpx
from pypdf import PdfReader


async def main():
    proof = Path("/proof")
    fixtures = json.loads((proof / "invitations-state.json").read_text())
    browser = json.loads((proof / "survey-invitation-browser.json").read_text())
    session = (proof / "session.env").read_text().strip().split("=", 1)[1]
    credentials = [session, browser["token"], *[row["token"] for row in fixtures]]
    products = ["responses_csv", "responses_xlsx", "analysis_xlsx", "analysis_pdf"]
    async with httpx.AsyncClient(
        base_url="http://api:8000",
        headers={"Cookie": f"__Host-leonaid_session={session}"},
        timeout=60,
    ) as client:

        async def call(method, path, body=None):
            result = await client.request(method, path, json=body)
            assert result.status_code == 200, (method, result.status_code)
            return result

        for fixture, answer in [
            (fixtures[0], "Attributable synthetic answer"),
            (browser, "Personal invitation works"),
        ]:
            path = f"/api/v1/surveys/{fixture['survey']}"
            versions = (await call("GET", path + "/analysis/versions")).json()
            snapshot = (
                await call(
                    "POST",
                    path + "/analysis",
                    {
                        "operationId": "credential-scan",
                        "filter": {
                            "versionId": versions["items"][0]["id"],
                            "statuses": ["in_progress", "partial", "completed"],
                        },
                    },
                )
            ).json()
            assert snapshot["participationCount"] == 1
            for product in products:
                job = (
                    await call(
                        "POST",
                        path + "/exports",
                        {
                            "operationId": "credential-scan-" + product,
                            "snapshotId": snapshot["id"],
                            "product": product,
                        },
                    )
                ).json()
                job_path = path + "/exports/" + job["id"]
                async with asyncio.timeout(90):
                    while True:
                        status = (await call("GET", job_path)).json()["status"]
                        assert status not in {"failed", "cancelled"}, (product, status)
                        if status == "available":
                            break
                        await asyncio.sleep(0.2)
                content = (await call("GET", job_path + "/download")).content
                if product == "responses_csv":
                    text = " ".join(
                        cell
                        for row in csv.reader(io.StringIO(content.decode("utf-8-sig")))
                        for cell in row
                    )
                elif product.endswith("xlsx"):
                    # Inspect every uncompressed member, including hidden metadata.
                    with ZipFile(io.BytesIO(content)) as archive:
                        text = " ".join(
                            archive.read(name).decode("utf-8", errors="replace")
                            for name in archive.namelist()
                        )
                else:
                    text = " ".join(
                        page.extract_text()
                        for page in PdfReader(io.BytesIO(content)).pages
                    )
                assert all(
                    value not in text and value.encode() not in content
                    for value in credentials
                ), "Credential in export"
                assert (answer in text) == product.startswith("responses_"), (
                    "Unexpected answer visibility"
                )
    (proof / "invitation-private-markers.json").write_text(
        json.dumps(
            [
                *credentials,
                "Attributable synthetic answer",
                "Personal invitation works",
            ]
        )
    )
    (proof / "invitation-privacy-proof.json").write_text(
        json.dumps(
            {
                "syntheticOnly": True,
                "attributableParticipations": 2,
                "actualWorkerDownloadsParsed": 8,
                "productsPerParticipation": products,
                "credentialsAbsentFromAllProducts": True,
                "answersPresentOnlyInRawProducts": True,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        "PASS: eight real invitation exports parsed; credentials absent, raw answers retained"
    )


asyncio.run(main())
