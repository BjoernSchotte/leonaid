# Browser actionability diagnostic acceptance

**100.1a / 100.S1a accepted.** This increment improves diagnostic evidence for
an unresolved Survey Journey failure; it does not fix or accept that journey,
the complete aggregate or the whole spike.

At source checkpoint `86bf028`, CI run `34187869648`, E2E job `101939764445`
failed its first pass after 309.839 seconds. The actual tested merge commit was
`52326b162e0dd2d5d8b5f3bc65fe82b9ba501ddf`. Artifact `10041248914` records a
timeout at `tests/e2e/surveys-journey.spec.mjs:206`, the Krapfentaxi freshness
input. The preceding `419738d` CI also failed there, in its second pass. Those
records do not distinguish a missing input from an actionability failure.

## Executed browser evidence

`tools/surveys/ci_diagnostics_browser.mjs` uses actual Chromium in the pinned
Playwright image, without network access or application services. Five distinct
DOM fixtures attempt a real keyboard press or pointer click: an absent element,
a hidden button, a disabled button, a pointer-intercepting overlay and an element
fixed outside the viewport. Each must throw Playwright's actual `TimeoutError`;
an unexpected success or different error fails the fixture command.

The first attempt's one-second timeouts ended before Chromium reported the
specific actionability reasons under current host load. That attempt did not
accept the new categories. With ten-second fixture timeouts, all five actual
errors contain the expected distinct fixed categories. No application or Journey
timeout was changed. The final browser command exited **0**; the five existing
privacy/collector tests also exited **0**.

The classifier exports only fixed category names and existing tracked source
locations. It does not serialize selectors, element HTML, arbitrary call logs,
answer text, URLs, cookies or screenshots. Each real selector contains a private
canary, and all five classified outputs were checked for its absence. Raw errors
remain in the ignored, private proof directory.

[Sanitized results and exact source/image hashes](assets/SURV-100-browser-diagnostics.json)
record the accepted cases. The retained fixture is byte-identical to the executed
private fixture. No new backend, Docker network, volume or host port was created;
the ephemeral browser container used `--rm --network none` and exited zero.

## Reproduction

Load `PLAYWRIGHT_IMAGE` from `infra/locks/images.env`. Create an owner-only ignored
proof directory, then run the image as the current UID/GID with `HOME=/tmp`, the
repository mounted read-only at `/workspace`, and that proof directory mounted
at `/proof`. Use `/workspace` as the working directory and execute:

```sh
node tools/surveys/ci_diagnostics_browser.mjs
```

Apply `tools/surveys/ci_diagnostics.py:classify` to each `raw` field in the local
`browser-errors.json`, with an empty public-file inventory. Compare each category
set with the committed result; require empty source locations and no canary in
the serialized output. A caught Playwright error's `stack` does not include its
`TimeoutError` name, so the fixture separately checks `error.name`; it does not
invent a timeout marker in the classifier output.

```sh
python3 tools/surveys/ci_diagnostics_test.py
```

The new categories are observations only. In particular, a locator-wait marker
without a resolved marker does not establish why the page lacked that element.
The original Journey test and production runner are unchanged by this increment.
