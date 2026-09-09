"""Extract fixed phase durations from Twenty logs without exposing their contents."""

from datetime import datetime
import subprocess
import sys

MARKERS = {
    "Running database setup and migrations...": ("twenty-migrations", "start"),
    "Successfully migrated DB!": ("twenty-migrations", "end"),
    "Registering background sync jobs...": ("twenty-cron-registration", "start"),
    "Successfully registered all background sync jobs!": (
        "twenty-cron-registration",
        "end",
    ),
}


def timings(log: str) -> list[tuple[str, float]]:
    starts: dict[str, datetime] = {}
    result = []
    for line in log.splitlines():
        timestamp, _, message = line.partition(" ")
        if message not in MARKERS:
            continue
        phase, event = MARKERS[message]
        instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if event == "start":
            starts[phase] = instant
        elif phase in starts:
            result.append((phase, (instant - starts.pop(phase)).total_seconds()))
    return result


if __name__ == "__main__":
    # Only this freshly owned container is read. Never copy raw logs into artifacts.
    logs = subprocess.run(
        ["docker", "logs", "--timestamps", sys.argv[1]],
        check=True,
        capture_output=True,
        text=True,
    )
    for name, seconds in timings(logs.stdout):
        print(f"test-phase: {name} seconds={seconds:.3f} exit=0")
