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
| Form Library / `survey-core` | `survey-library` tag `v3.0.3`, root MIT license | Pinned and verified at 3.0.3; see current acceptance below. |
| React renderer / `survey-react-ui` | Same MIT-licensed repository and tag | Pinned and verified at 3.0.3, aligned with core. |
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

## Implemented dependency disposition

The actual runtime selection is now pinned and verified. This replaces the
initial planning statement that no lockfile or distribution existed.

| Purpose | Implemented selection | Verification |
| --- | --- | --- |
| Respondent rendering | survey-core / survey-react-ui 3.0.3, MIT | Exact npm manifests and installed packed-consumer closure |
| React host runtime | React / React DOM 19.2.8 and scheduler 0.27.0, MIT | Exact consuming-host pins; neutral peer range ^19.2.8; narrow repository pin-policy exception |
| Drag-and-drop editor | Independently implemented HTML drag-and-drop with keyboard movement controls | No added editor/DnD runtime dependency; real editor browser journeys |
| Browser charts | Independently implemented CSS bars plus HTML tables | No chart runtime dependency; packed analytics entrypoint and chart/table agreement |
| XLSX data and charts | Existing openpyxl 3.1.5 with et-xmlfile 2.0.0 | Exact installed metadata, transitive requirements and reviewed notice fingerprints in the Python environment and actual API/worker images |
| PDF reports | Existing pinned Typst 0.13.1 with the dedicated survey template | Existing Typst pipeline; no SurveyJS PDF Generator; SURV-080 rendered report evidence |
| SurveyJS font assets | Open Sans, OFL-1.1 | Upstream installed package retains font license; respondent stylesheet is fontless and uses host fonts |

Both Python distributions declare MIT in their metadata. et-xmlfile additionally
redistributes `LICENCE.python` for its Python-derived code, including the PSF v2
and retained historical Python license notices. The gate admits the exact reviewed
file contents and does not label every bundled file MIT. The application images
retain those upstream distribution files; no source modification or relicensing
of these dependencies is introduced.

`./leonaid test-surveys-dependencies` runs the npm gate and the new XLSX runtime
gate. Unknown packages, versions, dependencies, commercial metadata, missing or
changed notice files, and omission of the separate Python notice are rejected.
`./leonaid test-surveys-package` independently installs the tarball outside the
workspace, checks its actual closure/notices/bundle boundaries, and exercises it
in Chromium across a backend restart. [Current acceptance evidence](proofs/SURV-000.md#complete-runtime-dependency-disposition).

This scope covers the survey package and the selected XLSX runtime closure, not
all pre-existing LeonAid dependencies or every base-image system library. The
existing host-only axe QA tooling remains separate and is not distributed with
the neutral package. Future dependency/version/asset additions must be reviewed
before extending either allowlist; a matching metadata license alone is not an
approval of new bundled notices. Final SURV-100 artifact review remains required.
Own project/editor license stays **UNDEFINED**, with existing manifest markers
preserved. No commercial fallback is permitted.

### Initial chart implementation

The initial choice/rating/matrix charts use independently implemented scoped
CSS bars with equivalent HTML data tables in the neutral `analytics` entrypoint.
No chart runtime package or commercial SurveyJS component is required. The
packed-consumer check verifies the entrypoint and excludes it from the respondent
bundle; [live UI and package evidence](proofs/SURV-070.md#analysis-ui-and-neutral-result-components).
Server-rendered report charts remain a separate SURV-080 deliverable. Own license
remains UNDEFINED.
