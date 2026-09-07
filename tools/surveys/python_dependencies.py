"""Admit exact XLSX runtime dependencies and the license texts they redistribute."""

from copy import deepcopy
import hashlib
from importlib.metadata import distribution
import json
from pathlib import Path

MIT = "0c84bb42f5d367e5ebf9fc2dde35b16141df5ee0fdc189250858bc6c5560f69e"
PYTHON = "4ccdaaebc0f44b83720ec0399bb7ab329adce067dd62f73c5535a2dc05628ab2"
APPROVED = {
    "openpyxl": {
        "version": "3.1.5",
        "license": "MIT",
        "requires": ["et-xmlfile"],
        "notices": {"LICENCE.rst": MIT},
    },
    "et-xmlfile": {
        "version": "2.0.0",
        "license": "MIT",
        "requires": [],
        "notices": {"LICENCE.rst": MIT, "LICENCE.python": PYTHON},
    },
}


def check(name, artifact):
    assert name in APPROVED, "Unreviewed XLSX dependency"
    assert artifact == APPROVED[name], "Unreviewed XLSX artifact or notice change"


def main():
    inventory = []
    for name in APPROVED:
        installed = distribution(name)
        artifact = {
            "version": installed.version,
            "license": installed.metadata.get("License"),
            "requires": sorted(installed.requires or []),
            "notices": {
                path.name: hashlib.sha256(
                    installed.locate_file(path).read_bytes()
                ).hexdigest()
                for path in installed.files or []
                if "LICEN" in str(path).upper()
            },
        }
        check(name, artifact)
        inventory.append({"name": name, **artifact})

    negatives = [("unknown-xlsx", APPROVED["openpyxl"])]
    for field, value in (
        ("version", "3.1.6"),
        ("license", "Commercial"),
        ("license", "UNKNOWN"),
        ("requires", ["et-xmlfile", "unknown-transitive"]),
        ("notices", {}),
        ("notices", {"LICENCE.rst": "changed"}),
    ):
        artifact = deepcopy(APPROVED["openpyxl"])
        artifact[field] = value
        negatives.append(("openpyxl", artifact))
    without_python = deepcopy(APPROVED["et-xmlfile"])
    del without_python["notices"]["LICENCE.python"]
    negatives.append(("et-xmlfile", without_python))
    for name, artifact in negatives:
        try:
            check(name, artifact)
        except AssertionError:
            continue
        raise AssertionError("Dependency admission accepted a negative fixture")

    output = Path(".artifacts/surveys/python-dependencies.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"inventory": inventory, "negativeCases": len(negatives)}, indent=2)
        + "\n"
    )
    print(
        "PASS: exact XLSX runtime closure, retained MIT/Python notices and eight negative admission cases"
    )


if __name__ == "__main__":
    main()
