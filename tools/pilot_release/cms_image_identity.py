"""Embed CMS identity at build time and compare it before runtime activation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.pilot_release.cms_identity import create_cms_identity, validate_cms_identity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("build", "verify"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        expected = create_cms_identity(arguments.root)
        if arguments.mode == "build":
            if arguments.output is None:
                raise ValueError("output_required")
            arguments.output.write_text(
                json.dumps(expected, sort_keys=True) + "\n", encoding="utf-8"
            )
        else:
            if arguments.output is not None:
                raise ValueError("verification_is_read_only")
            actual = json.load(sys.stdin)
            validate_cms_identity(actual)
            if actual != expected:
                raise ValueError("image_identity_mismatch")
        print("cms-image-identity: verified; no activation or migration")
        return 0
    except (ValueError, KeyError, TypeError, OSError):
        print("cms-image-identity: refused; CMS must remain stopped", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
