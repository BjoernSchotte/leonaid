# Task status reconciliation

Reviewed against source checkpoint `54e8c3b` and existing recorded live evidence.
This is a documentation review, not a new execution of the recovery suite.

## 090.2a: accepted operator portion

The [recorded full Restic run](SURV-090.md#full-restic-backup-and-fresh-target-restore)
and its [sanitized result](assets/SURV-090-restic-recovery.json) cover each direct
acceptance assertion. The current harness and probe retain those assertions:

| Required assertion                            | Evidence and source check                                                                                                                                                                                                              |
| --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Encrypted backup and manifest validation      | Actual `tools/backup/backup.sh` and `restore.sh` commands completed in the recorded run; the original survey answer and exact object were inspected after restoration, ruling out an earlier manifest failure as the rejection result. |
| Post-backup deletion                          | The source was populated and backed up before the real deletion; its newer authenticated checkpoint was retained before source-project removal.                                                                                        |
| Missing checkpoint blocks startup             | `tools/surveys/restic_recovery.sh` requires exit 1 and no running API/public/proxy/worker; `recovery_live.py` verifies the restored SQL answer and export object remain offline.                                                       |
| Valid checkpoint erases restored content      | The second actual restore runs with the valid checkpoint; the probe verifies relational and exact object-version removal and old authenticated/public access returning 404.                                                            |
| No-build restoration preserves image identity | The harness captures all six built service image IDs, passes `LEONAID_RESTORE_NO_BUILD=true` and compares every running target image ID with its source ID.                                                                            |
| Supporting browser and teardown proof         | The recorded Chromium foundation case passed, and target container/volume absence was checked. This is not complete recovery browser coverage or independent physical host-loss proof.                                                 |

The implementation checklist now agrees with the plan's accepted **090.2a**.
**090.2, 090.2b and 090.A3 remain open** for the documented independent cutoff,
unexpected host-loss and preceding-backup/release compatibility requirements.

## 100.2: keep the parent task open

The [complete dropdown/journey proof](SURV-100-DROPDOWN.md) accepts **100.2a** and
the complete desktop/mobile browser journey portion. The parent **100.2** also
requires **100.A4**, including capability and task traceability. That review is
still open. PLAN.md now matches IMPLEMENTATION-TASKS.md by leaving **100.2**
unchecked; the narrower passing browser result remains recorded.
