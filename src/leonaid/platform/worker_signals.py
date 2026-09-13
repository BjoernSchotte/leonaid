"""Process-local evidence of completed worker activity, without business payloads."""

from __future__ import annotations

import time
from typing import Literal

Activity = Literal["queue_poll", "job_completion", "survey_sweep"]
_last_success: dict[Activity, float] = {}


def record_success(activity: Activity) -> None:
    """Record only after the corresponding operation has returned successfully."""
    _last_success[activity] = time.time()


def render_activity_metrics() -> str:
    """Zero means no successful activity observed since this process started."""
    snapshot = _last_success.copy()
    lines = [
        "# HELP leonaid_worker_last_success_timestamp_seconds Last successful activity in this process; zero means not observed.",
        "# TYPE leonaid_worker_last_success_timestamp_seconds gauge",
    ]
    activities: tuple[Activity, ...] = ("queue_poll", "job_completion", "survey_sweep")
    for activity in activities:
        lines.append(
            "leonaid_worker_last_success_timestamp_seconds"
            f'{{activity="{activity}"}} {snapshot.get(activity, 0.0)}'
        )
    return "\n".join(lines) + "\n"
