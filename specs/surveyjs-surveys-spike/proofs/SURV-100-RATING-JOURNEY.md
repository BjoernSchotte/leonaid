# SURV-100 — Selected-rating assertions and complete Journey repetition

The Journey helper now verifies the selected value after its pointer/keyboard
action: a dropdown displays the requested value and a radio is actually checked.
Previously, a successful `press("Space")` could let the helper return even when
no rating was selected. Both assertions stay inside the existing retry loop;
the 15-second budget, 100/250 ms retry intervals and one-second actions are unchanged.
No production runner code or business assertion is relaxed.

A controlled Chromium diagnostic uses the actual runner with a simulated save
adapter and deliberately hides the rating for one second. At widths 1440 and
390, the old helper returns without saving a rating; the next-page action stays
on the required question with one validation error. The strengthened helper
waits/retries until rating 5 is selected and saved, and the next page opens without
that validation error. This demonstrates the helper defect under the controlled
condition. It does not establish that the same condition caused historical CI failures.

The complete real-service command then passed:

```sh
sh tools/surveys/infrastructure.sh "$PWD" journeys
```

Exit **0**, total **495.847 seconds**, with **five Chromium tests passing in the
reported 1.2 minutes**: foundation plus complete Krapfentaxi and Golf journeys at
1440×960 and 390×960. The [reviewed evidence](assets/SURV-100-rating-journey.json)
records source checkpoint `8a9e107`, exact hashes of the changed test and unchanged
runner/harness/verifier, controlled observations and actual journey assertions.

Each journey performs authoring/publication, participation, partial response
resume and version isolation, outsider rejection, analysis, four downloads and
erasure. The independent verifier parses all **16 actual browser downloads**:
response CSV and XLSX agree; analysis XLSX metrics match the selected snapshot;
the PDF contains the snapshot/counts; analysis products omit the response free
text. It queries the real database for absent survey content and lists every
object version and delete marker under each survey prefix to prove complete erasure.

The harness and controller finish with zero owned containers, volumes and
networks. A separate post-run inspection confirms the same empty inventories.
The run used a fresh checksum/PID project, reserved unused networks and no
published host ports. Code outside the `rate` helper is unchanged.

This accepts the strengthened helper and its complete local regression. Existing
100.A2/100.S4 journey acceptance is corroborated; the final repeated aggregate,
remaining regression suites and independent host-loss recovery stay open. The
earlier CI failures remain historical observations with an unresolved cause.
