"""Activity metrics are separate from database connectivity and reset on restart."""

import json
import os
from pathlib import Path
import subprocess
import sys


def test_fresh_process_activity_metrics_record_only_observed_success() -> None:
    script = """
import json
import time
from leonaid.platform.worker_signals import last_success_at, record_success, render_activity_metrics
assert last_success_at("survey_sweep") is None
before = render_activity_metrics()
started = time.time()
record_success("queue_poll")
assert last_success_at("survey_sweep") is None
record_success("survey_sweep")
from datetime import datetime
assert datetime.fromisoformat(last_success_at("survey_sweep")).timestamp() >= started
after = render_activity_metrics()
print(json.dumps([before, after, started, time.time()]))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "PYTHONPATH": str(Path("src").resolve())},
        check=True,
        capture_output=True,
        text=True,
    )
    before, after, started, finished = json.loads(result.stdout)
    for activity in ("queue_poll", "job_completion", "survey_sweep"):
        assert f'{{activity="{activity}"}} 0.0' in before
    assert '{activity="job_completion"} 0.0' in after
    assert '{activity="survey_sweep"} 0.0' not in after
    value = next(
        line.rsplit(" ", 1)[1]
        for line in after.splitlines()
        if '{activity="queue_poll"}' in line
    )
    assert started <= float(value) <= finished
