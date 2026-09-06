# SurveyJS dependency and license review

Checked: 2026-09-06. Own LeonAid/editor license: **UNDEFINED**.
Scope: upstream components for this spike, not a license audit of all LeonAid.

## Decision

Commercial components are excluded. The initial SurveyJS software allowlist is
`survey-core` and `survey-react-ui`, from the MIT-licensed Form Library project.
OFL-1.1 fonts are explicitly allowed as separately licensed assets.
Use independently implemented editing and analytics, and the existing Typst
integration for reports. A publicly readable repository is not sufficient
evidence of a permissive license.

## Checked upstream components

| Component | Evidence and classification | Spike disposition |
|---|---|---|
| Form Library / `survey-core` | `survey-library` tag `v3.0.3`, root MIT license | Allowed candidate; pin and verify the actual npm artifact in SURV-000. |
| React renderer / `survey-react-ui` | Same MIT-licensed repository and tag | Allowed candidate, aligned with core version. |
| Form Library theme/token and adapter SCSS | Located under `packages/survey-core/src/themes/adapters/` in the MIT repository | May be used under that license; separately inspect imported assets. This does not approve entire demo repositories. |
| Bundled Open Sans fonts | Separate SIL Open Font License 1.1 in `packages/survey-core/src/fonts/LICENSE.txt` | Allowed font asset under OFL-1.1; retain its copyright and license notices. No commercial license required. |
| Survey Creator, including core and framework wrappers | Repository LICENSE is a commercial developer EULA | Excluded: no `survey-creator-core`, `survey-creator-react`, other Creator wrappers or derived editor code. |
| SurveyJS Dashboard / `survey-analytics` | Repository LICENSE is the commercial developer EULA | Excluded, including its charting, saved-view and cross-filtering implementation. |
| SurveyJS PDF Generator / `survey-pdf` | Repository LICENSE is the commercial developer EULA | Excluded. Typst analysis reports remain an independent implementation. |

The Form Library's multipage rendering, client logic and events do not require
Creator or Dashboard. Server loading, autosave, timeout classification, access
control and aggregates are supplied by our adapters. SurveyJS 3 does not change
that architecture. The overview's Creator UI Preset Editor and Dashboard/PDF
enhancements must not be mistaken for MIT Form Library features.

Open Sans may be embedded and redistributed under OFL-1.1. Keep the font
copyright and license notices; do not sell the font on its own, and check the
reserved-name conditions if modifying it. The font stays under OFL, but this
does not impose OFL on our application code or generated reports. Do not
describe all files in the MIT repository as MIT. No font replacement is
required merely because the font license differs from the software license.

## Evidence

Read the release's license and component manifests, inspected its source tree,
and checked the separate font license. Commercial repository license texts were
checked separately; fixed revisions below preserve the research references.

- [Form Library MIT license, v3.0.3](https://github.com/surveyjs/survey-library/blob/v3.0.3/LICENSE)
- [Core manifest, v3.0.3](https://github.com/surveyjs/survey-library/blob/v3.0.3/packages/survey-core/package.json)
- [React manifest, v3.0.3](https://github.com/surveyjs/survey-library/blob/v3.0.3/packages/survey-react-ui/package.json)
- [Core theme adapters](https://github.com/surveyjs/survey-library/tree/v3.0.3/packages/survey-core/src/themes/adapters)
- [Open Sans license](https://github.com/surveyjs/survey-library/blob/v3.0.3/packages/survey-core/src/fonts/LICENSE.txt)
- [Creator license](https://github.com/surveyjs/survey-creator/blob/4cee1df6a5630f9ea7bab9d259da9f3031628a2d/LICENSE)
- [Dashboard license](https://github.com/surveyjs/survey-analytics/blob/e0e2aad0abcb34cd5f2debc6f5bba48817c4da2a/LICENSE)
- [PDF Generator license](https://github.com/surveyjs/survey-pdf/blob/06b9a1cce6a13c668794ec0a774309cf3a9ef74d/LICENSE)
- [Official product licensing distinction](https://surveyjs.io/licensing)

## Implementation gates still open

This review establishes the component boundary. It is not a completed audit of
a lockfile or final distribution: neither exists for the new package yet.

1. Pin compatible core/React versions; inspect registry tarballs, license files,
   dependencies and resolved transitive versions. Repeat for any later upgrade.
2. Select permissive drag-and-drop, chart and XLSX dependencies; record their
   exact versions and license evidence before introducing them. Do not assume
   that a chart engine's permissive license also covers SurveyJS Dashboard.
3. Maintain a machine-checkable allowlist and fail on unknown, commercial or
   incompatible software licenses. Cover runtime, demo and added build/test
   dependencies, plus imported source snippets and assets.
4. Inspect package contents and browser bundles for prohibited SurveyJS products,
   font assets and their notices, external requests and accidental dependencies from examples.
   Preserve applicable third-party notices in distributed artifacts.
5. Keep our own license marker UNDEFINED in planning documents. Do not substitute
   it for an SPDX identifier or overwrite existing private/UNLICENSED metadata.

Track these gates in SURV-000, SURV-020 and final SURV-100 evidence in
[PLAN.md](PLAN.md). No commercial fallback is permitted if our custom editor
requires more effort; record the remaining work instead.
