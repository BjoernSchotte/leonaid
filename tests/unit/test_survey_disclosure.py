"""Minimum group size (k = 5) for shown survey aggregates."""

from uuid import uuid4

from leonaid.modules.surveys.application.disclosure import K, disclose, protect


def bucket(value, count, answered):
    return {
        "value": value,
        "label": f"Option {value}",
        "count": count,
        "percentage": count / answered * 100 if answered else None,
    }


def question(qid, kind, counts, *, answered=None, rows=(), stats=None):
    answered = sum(counts) if answered is None else answered
    return {
        "questionId": qid,
        "title": qid,
        "kind": kind,
        "relevant": answered,
        "answered": answered,
        "unanswered": 0,
        "hidden": 0,
        "invalid": 0,
        "counts": [bucket(i, c, answered) for i, c in enumerate(counts)],
        "sum": None,
        "mean": None,
        "minimum": None,
        "maximum": None,
        "nps": None,
        **(stats or {}),
        "matrixRows": list(rows),
    }


def snapshot(total, questions, statuses=None, pages=None):
    statuses = statuses or {"in_progress": 0, "partial": 0, "completed": total}
    for q in questions:
        q["relevant"] = total - q["hidden"]
        q["unanswered"] = q["relevant"] - q["answered"] - q["invalid"]
        for row in q["matrixRows"]:
            row["unanswered"] = q["relevant"] - row["answered"] - row["invalid"]
    return {
        "id": str(uuid4()),
        "surveyId": str(uuid4()),
        "createdAt": "2026-11-04T10:00:00+00:00",
        "filter": {
            "versionId": str(uuid4()),
            "statuses": ["partial", "completed"],
            "isTest": False,
            "createdFrom": None,
            "createdBefore": None,
        },
        "versionNumber": 1,
        "rendererVersion": "3.0.3",
        "capabilityProfile": "initial-v1",
        "participationCount": total,
        "statusCounts": statuses,
        "lastPageCounts": pages
        or [{"pageId": "main", "title": "Seite", "count": total}],
        "questions": questions,
    }


def test_protect_withholds_by_value_once_anything_is_withheld():
    assert protect([0, 7, 9], 16) == [False, False, False]
    # Once a count of 1-4 is withheld, every cell below 2K goes with it.
    assert protect([3, 7, 9, 12], 31) == [True, True, True, False]
    # I3: two withheld 1s would be pinned down by "2 left for 2 cells".
    assert protect([10, 1, 1], 12) == [True, True, True]
    assert protect([10, 1, 1, 1], 13) == [True, True, True, True]
    # Zeros too: shown zeros would tell which withheld cells hold someone.
    assert protect([0, 2, 12, 20], 34) == [True, True, True, False]
    # Without a known total (multiple choice) only the small counts.
    assert protect([3, 7, 9], None) == [True, False, False]


def test_small_selection_shows_no_results():
    shown = disclose(snapshot(4, [question("q", "radiogroup", [1, 3])]))
    assert shown.suppressed and shown.minimumGroupSize == K
    q = shown.questions[0]
    assert q.suppressed and q.counts == [] and q.mean is None


def test_question_below_k_answers_has_no_distribution_or_statistics():
    rating = question(
        "rating",
        "rating",
        [2, 2],
        stats={"sum": 6.0, "mean": 1.5, "minimum": 1.0, "maximum": 2.0},
    )
    shown = disclose(snapshot(10, [rating]))
    q = shown.questions[0]
    assert not shown.suppressed
    assert q.suppressed and q.counts == []
    assert (q.mean, q.minimum, q.maximum, q.nps) == (None,) * 4
    assert (q.answered, q.unanswered) == (4, 6)  # denominators stay
    assert "sum" not in q.model_dump()  # M8


def test_single_choice_withholds_small_and_complementary_counts():
    shown = disclose(snapshot(20, [question("q", "radiogroup", [2, 6, 12])]))
    counts = [(c.count, c.percentage, c.suppressed) for c in shown.questions[0].counts]
    assert counts == [(None, None, True), (None, None, True), (12, 60.0, False)]


def test_derived_figures_go_with_a_withheld_count():
    """C2: rating [0,1,4,7,8] with sum and mean would solve c2 and c3."""
    rating = question(
        "r",
        "rating",
        [0, 1, 4, 7, 8],
        stats={"sum": 82.0, "mean": 4.1, "minimum": 2.0, "maximum": 5.0},
    )
    q = disclose(snapshot(20, [rating])).questions[0]
    assert [c.count for c in q.counts] == [None, None, None, None, None]
    assert (q.mean, q.minimum, q.maximum, q.nps) == (None,) * 4
    clean = question(
        "r",
        "rating",
        [0, 0, 10, 10, 10],
        stats={"mean": 4.0, "minimum": 3.0, "maximum": 5.0},
    )
    q = disclose(snapshot(30, [clean])).questions[0]
    assert (q.mean, q.minimum, q.maximum) == (4.0, 3.0, 5.0)


def test_conditional_denominators_follow_their_condition():
    """C3: Q1 [2, 18] withheld must not come back as Q2's shown/hidden."""
    gate = question("gate", "radiogroup", [2, 18])
    follow = question("follow", "radiogroup", [1, 1])
    follow["hidden"] = 18
    stored = snapshot(20, [gate, follow])
    stored["dependencies"] = {"questions": {"follow": ["gate"]}, "pages": {}}
    shown = disclose(stored)
    q = shown.questions[1]
    assert q.suppressed
    assert (q.relevant, q.hidden, q.answered, q.unanswered) == (None,) * 4
    # A snapshot from before the references were recorded: the same.
    del stored["dependencies"]
    q = disclose(stored).questions[1]
    assert (q.relevant, q.hidden) == (None, None)


def test_multiple_choice_is_protected_like_a_known_total():
    """N2: everyone who answers picks at least one option, so the cells are
    bounded by "answered"; a lone small cell would follow from the others."""
    shown = disclose(snapshot(10, [question("q", "checkbox", [2, 6, 9], answered=10)]))
    assert [c.count for c in shown.questions[0].counts] == [None, None, None]
    shown = disclose(
        snapshot(30, [question("q", "checkbox", [2, 16, 29, 12], answered=30)])
    )
    # 2 is small, and 29 of 30 leaves 1 who did not tick it (complement).
    assert [c.count for c in shown.questions[0].counts] == [None, 16, None, 12]
    # Reviewer case: answered 9, A=5, B=4, C=0 -> B was pinned at 4.
    shown = disclose(snapshot(9, [question("q", "checkbox", [5, 4, 0], answered=9)]))
    assert [c.count for c in shown.questions[0].counts] == [None, None, None]


def test_matrix_rows_follow_the_same_rules():
    rows = [
        {
            "rowId": "r1",
            "label": "Organisation",
            "answered": 10,
            "unanswered": 0,
            "invalid": 0,
            "counts": [bucket("good", 9, 10), bucket("bad", 1, 10)],
        },
        {
            "rowId": "r2",
            "label": "Verpflegung",
            "answered": 3,
            "unanswered": 0,
            "invalid": 0,
            "counts": [bucket("good", 3, 3), bucket("bad", 0, 3)],
        },
    ]
    matrix = question("m", "matrix", [], answered=10, rows=rows)
    shown = disclose(snapshot(10, [matrix])).questions[0]
    first, second = shown.matrixRows
    assert [c.count for c in first.counts] == [None, None]
    assert second.suppressed and second.counts == []


def test_status_and_last_page_counts_are_person_counts_too():
    shown = disclose(
        snapshot(
            12,
            [],
            statuses={"in_progress": 2, "partial": 3, "completed": 9},
            pages=[
                {"pageId": "a", "title": "A", "count": 1},
                {"pageId": "b", "title": "B", "count": 11},
            ],
        )
    )
    assert shown.statusCounts.in_progress is None
    # partial 3 is small; completed 9 would reveal it (12 - 9): both withheld.
    assert (shown.statusCounts.partial, shown.statusCounts.completed) == (None, None)
    # Last pages say where people stopped, like the denominators (R5); with
    # nothing withheld in the answers they are shown.
    assert [page.count for page in shown.lastPageCounts] == [1, 11]


def test_small_selection_hides_its_size():
    """M1: 3 participations read as withheld, not as "3"."""
    shown = disclose(snapshot(3, [question("q", "radiogroup", [3])]))
    assert shown.suppressed and shown.participationCount is None
    assert (
        disclose(snapshot(0, [question("q", "radiogroup", [0])])).participationCount
        == 0
    )


def test_large_counts_pass_unchanged():
    stored = snapshot(30, [question("q", "radiogroup", [0, 10, 20])])
    shown = disclose(stored)
    assert [c.count for c in shown.questions[0].counts] == [0, 10, 20]
    assert shown.statusCounts.completed == 30
    assert shown.lastPageCounts[0].count == 30


def test_whole_days_snap_to_berlin_days_and_stop_before_today():
    from datetime import datetime, timezone

    from leonaid.modules.surveys.application.disclosure import whole_days

    # 12:00 UTC on 4 Nov 2026 is 13:00 in Berlin (CET, UTC+1).
    now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
    today = "2026-11-03T23:00:00+00:00"  # 4 Nov, 00:00 Berlin
    assert whole_days(None, None, now) == (None, today)
    # A start mid-day snaps to 00:00 Berlin of that day.
    assert whole_days("2026-10-01T13:00:00+00:00", None, now) == (
        "2026-09-30T22:00:00+00:00",  # 1 Oct 00:00 CEST
        today,
    )
    # An end mid-day snaps to 24:00 of that day; an aligned end stays.
    assert whole_days(None, "2026-10-10T05:00:00+00:00", now)[1] == (
        "2026-10-10T22:00:00+00:00"
    )
    assert whole_days(None, "2026-10-09T22:00:00+00:00", now)[1] == (
        "2026-10-09T22:00:00+00:00"
    )
    # Never into the current day, even with a later end.
    assert whole_days(None, "2026-11-04T11:00:00+00:00", now)[1] == today
    assert whole_days(None, "2099-01-01T00:00:00+00:00", now)[1] == today
    # A start today leaves nothing: start == end (the caller refuses it).
    start, end = whole_days("2026-11-04T09:00:00+00:00", None, now)
    assert start == end == today
    # The clocks change on 25 Oct: that day has 25 hours.
    assert whole_days(
        "2026-10-25T12:00:00+00:00", "2026-10-25T12:00:00+00:00", now
    ) == (
        "2026-10-24T22:00:00+00:00",
        "2026-10-25T23:00:00+00:00",
    )


def test_nps_segments_follow_the_same_rules():
    counts = [1, 0, 0, 0, 0, 0, 2, 3, 3, 6, 5]  # 0..10
    nps = question("nps", "rating", counts, stats={"nps": 40.0})
    q = disclose(snapshot(20, [nps])).questions[0]
    # C2: a withheld score takes the NPS and its segments with it.
    assert q.npsSegments is None and q.nps is None
    full = question(
        "nps", "rating", [0, 0, 0, 0, 0, 0, 6, 0, 8, 0, 16], stats={"nps": 33.3}
    )
    q = disclose(snapshot(30, [full])).questions[0]
    assert q.npsSegments is not None
    assert (
        q.npsSegments.detractors,
        q.npsSegments.passives,
        q.npsSegments.promoters,
    ) == (6, 8, 16)
    plain = question("r", "rating", [5, 5])
    assert disclose(snapshot(10, [plain])).questions[0].npsSegments is None


def test_report_exports_show_withheld_counts():
    import io

    from openpyxl import load_workbook

    from leonaid.modules.surveys.adapters.survey_tabular_exports import (
        render_tabular,
    )
    from leonaid.modules.surveys.adapters.typst.survey_renderer import (
        render_payload,
    )
    from leonaid.modules.surveys.application.analysis_snapshot import (
        AnalysisSnapshot as Stored,
    )
    from leonaid.modules.surveys.application.export_rendering import (
        SurveyExportSource,
    )

    few = question("few", "rating", [2, 2], stats={"mean": 1.5})
    few["hidden"] = 16
    stored = snapshot(20, [question("q", "radiogroup", [2, 6, 12]), few])
    # The export adapter passes the disclosed snapshot to the PDF renderer.
    pdf = render_payload(SurveyExportSource("T", disclose(stored)))
    full = render_payload(SurveyExportSource("T", Stored.model_validate(stored)))
    assert [r["count"] for r in full["questions"][0]["groups"][0]["rows"]] == [
        2,
        6,
        12,
    ]
    rows = pdf["questions"][0]["groups"][0]["rows"]
    assert [row["count"] for row in rows] == ["–", "–", 12]
    assert pdf["questions"][1]["groups"] == []
    assert any(m["label"] == "Hinweis" for m in pdf["questions"][1]["metrics"])
    # Report workbook: the same "–" and the k note in the metadata.
    workbook = load_workbook(
        io.BytesIO(
            render_tabular(
                "analysis_xlsx", SurveyExportSource("T", disclose(stored))
            ).content
        )
    )
    cells = [c.value for row in workbook["Distributions"].iter_rows() for c in row]
    assert cells.count("–") == 2 and 12 in cells
    meta = [c.value for row in workbook.worksheets[0].iter_rows() for c in row]
    assert "minimum_group_size" in meta


def test_settled_selection_needs_an_end_and_completed_only():
    import asyncio

    import pytest

    from leonaid.modules.surveys.adapters.postgres.survey_analysis import (
        create_snapshot,
    )
    from leonaid.modules.surveys.application.analysis_snapshot import (
        AnalysisFilter,
    )

    version = str(uuid4())
    for unsettled in (
        AnalysisFilter(versionId=version, statuses=["completed"]),
        AnalysisFilter(
            versionId=version,
            statuses=["partial", "completed"],
            createdBefore="2026-11-03T23:00:00+00:00",
        ),
    ):
        with pytest.raises(ValueError, match="settled"):
            asyncio.run(create_snapshot(None, None, unsettled, settled=True))


def test_reports_rendered_before_the_k_rule_are_never_delivered():
    """M4: a stored report from before k = 5 may hold counts 1 to 4."""
    from leonaid.modules.surveys.adapters import survey_tabular_exports
    from leonaid.modules.surveys.adapters.typst import survey_renderer
    from leonaid.modules.surveys.application.export_rendering import (
        disclosed_render,
    )

    from leonaid.modules.surveys.application.export_rendering import (
        DISCLOSED_SINCE,
    )

    # The guard tracks the current renderers exactly: a version bump for
    # new disclosure rules must raise DISCLOSED_SINCE with it.
    for product, current in [
        ("analysis_pdf", survey_renderer.RENDER_VERSION),
        ("analysis_xlsx", survey_tabular_exports.RENDER_VERSION),
    ]:
        prefix, since = DISCLOSED_SINCE[product]
        assert current.startswith(f"{prefix}{since}"), (product, current)
        assert disclosed_render(product, current)
    assert disclosed_render("analysis_pdf", "survey-analysis-v10+typst-0.14.2")
    # Older, unknown or foreign versions are refused (fails closed). The
    # previous versions predate review round 2 (N1, N2, N3).
    for product, version in [
        ("analysis_pdf", "survey-analysis-v3+typst-0.14.2"),
        ("analysis_xlsx", "survey-tabular-v4"),
        ("analysis_pdf", "survey-analysis-v2+typst-0.14.2"),
        ("analysis_xlsx", "survey-tabular-v3"),
        ("analysis_pdf", "survey-analysis-v1+typst-0.14.2"),
        ("analysis_pdf", "survey-analysis-vX+typst"),
        ("analysis_pdf", "survey-tabular-v3"),
        ("analysis_xlsx", "survey-tabular-v2"),
        ("analysis_xlsx", ""),
        ("analysis_docx", "survey-tabular-v3"),
    ]:
        assert not disclosed_render(product, version), (product, version)
    # Raw exports are raw by design.
    assert disclosed_render("responses_csv", "survey-tabular-v1")


def test_a_number_never_shows_its_extremes():
    """R6 (M2): minimum and maximum are single people's values."""
    hours = question(
        "h",
        "number",
        [],
        answered=30,
        stats={"mean": 15.5, "minimum": 1.0, "maximum": 30.0},
    )
    q = disclose(snapshot(30, [hours])).questions[0]
    assert (q.minimum, q.maximum) == (None, None)
    assert q.mean == 15.5


def test_conditions_are_recorded_by_structure():
    """N1: each comparison of a visibleIf, with its page's, in the snapshot."""
    from leonaid.modules.surveys.adapters.postgres.survey_analysis import (
        dependencies,
    )

    definition = {
        "pages": [
            {
                "name": "p1",
                "elements": [
                    {"name": "g1"},
                    {"name": "g2"},
                    {"name": "f", "visibleIf": "({g1} = 'yes' and {g2} = 'yes')"},
                    {"name": "h", "visibleIf": "{g1} notempty"},
                ],
            },
            {
                "name": "p2",
                "visibleIf": "{g2} = 'no'",
                "elements": [{"name": "x"}, {"name": "y", "visibleIf": "{g1} != 'a'"}],
            },
        ]
    }
    recorded = dependencies(definition)
    assert recorded["questionLeaves"] == {
        "f": [["g1", "=", "'yes'"], ["g2", "=", "'yes'"]],
        "h": [["g1", "notempty", ""]],
        "x": [["g2", "=", "'no'"]],
        "y": [["g2", "=", "'no'"], ["g1", "!=", "'a'"]],
    }
    assert recorded["pageLeaves"] == {"p2": [["g2", "=", "'no'"]]}
    assert recorded["questions"]["y"] == ["g1", "g2"]
