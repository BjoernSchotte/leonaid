# CI output capture preserves UTF-8 stream boundaries

The Security job on `562de8b` passes every scanner and application-security
command, including Chromium and owned-resource cleanup, then exits **70** when
artifact validation rejects `command.log` as invalid UTF-8. Its GitHub log shows
a Trivy version notice inserted between partial bytes of a Unicode table border.
GitHub's log transport replaces the invalid bytes; the original command artifact
was correctly discarded and is not claimed to be recoverable.

`run-job.sh` previously merged stdout and stderr before `tee`. The new
`capture-command.sh` drains the channels independently, preserving each stream's
bytes, while retaining live console output. After both collectors finish, it
writes explicitly labelled stdout/stderr sections to `command.log`. This file
preserves order within each channel; it does not claim cross-channel chronology.
Command exit status is retained and capture/write failure returns nonzero.
The sanitizer, UTF-8 requirement, scanner flags and vulnerability thresholds are
unchanged. The Security command additionally runs the new process tests.

## Verification

- `python3 tools/ci/capture_command_test.py .`: five tests pass on macOS and
  again in the pinned Linux Python image. Actual writes deterministically make
  the old merged stream invalid and the new separated capture valid. Other
  tests cover command exit 23, large output on both channels, genuinely invalid
  original bytes and an unwritable destination.
- Existing workflow-contract, sanitizer and no-test-doubles checks pass.
- The complete `run-job.sh` wrapper runs the pinned real Trivy scanner against
  the previously verified Caddy OCI archive with the existing severity and
  exit policy. Scanner and wrapper exit **0**; the unchanged sanitizer accepts
  both resulting artifacts. An isolated private cache is used; no application
  stack or host port is required.
- A second actual wrapper invocation emits invalid original bytes. It exits
  **70**, removes `command.log` and leaves only the fixed sanitization-failure
  marker. Invalid input is not silently replaced or accepted.

[Exact source hashes and results](assets/SURV-100-ci-output-capture.json) identify
the tested dirty inputs relative to `562de8b`. The full corrected branch CI must
still pass; this scoped repair does not accept the aggregate or the full spike.
