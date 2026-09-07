"""Test-only abrupt exit after a real archive publication durability boundary."""

import asyncio
from argparse import Namespace
import os
from pathlib import Path
import sys

import leonaid.adapters.storage.survey_checkpoint_archive as archive
from recovery import execute

original = archive.atomic_write
target = {"after-pending": "pending.json", "after-current": "current.json"}[sys.argv[1]]


def interrupted(path, document):
    original(path, document)
    if path.name == target:
        os._exit(73)


archive.atomic_write = interrupted
asyncio.run(execute(Namespace(command="publish", archive=Path("/archive"))))
raise AssertionError("Publication did not reach the requested crash boundary")
