#!/usr/bin/env python3
"""Run independent Python contract scripts without creating a container per file."""

import subprocess
import sys


for contract in sys.argv[1:]:
    print(f"contract-runner: {contract}", flush=True)
    subprocess.run([sys.executable, contract], check=True)
