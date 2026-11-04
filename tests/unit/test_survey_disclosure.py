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


def test_protect_withholds_small_counts_and_one_more_when_derivable():
    assert protect([0, 7, 9], 16) == [False, False, False]
    assert protect([3, 7, 9], 19) == [True, True, False]
    # Two withheld counts cannot be told apart by subtraction.
    assert protect([3, 2, 9], 14) == [True, True, False]
    # Without a known total (multiple choice) nothing extra is needed.
    assert protect([3, 7, 9], None) == [True, False, False]
    # Zero is never the extra one: it reveals no one.
    assert protect([0, 2, 12], 14) == [False, True, True]


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
    rating["hidden"] = 6
    shown = disclose(snapshot(10, [rating]))
    q = shown.questions[0]
    assert not shown.suppressed
    assert q.suppressed and q.counts == []
    assert (q.sum, q.mean, q.minimum, q.maximum, q.nps) == (None,) * 5
    assert q.answered == 4  # denominators stay


def test_single_choice_withholds_small_and_complementary_counts():
    shown = disclose(snapshot(20, [question("q", "radiogroup", [2, 6, 12])]))
    counts = [(c.count, c.percentage, c.suppressed) for c in shown.questions[0].counts]
    assert counts == [(None, None, True), (None, None, True), (12, 60.0, False)]


def test_multiple_choice_withholds_only_small_counts():
    shown = disclose(
        snapshot(10, [question("q", "checkbox", [2, 6, 9], answered=10)])
    )
    assert [c.count for c in shown.questions[0].counts] == [None, 6, 9]


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
    assert [page.count for page in shown.lastPageCounts] == [None, None]


def test_large_counts_pass_unchanged():
    stored = snapshot(30, [question("q", "radiogroup", [0, 10, 20])])
    shown = disclose(stored)
    assert [c.count for c in shown.questions[0].counts] == [0, 10, 20]
    assert shown.statusCounts.completed == 30
    assert shown.lastPageCounts[0].count == 30


def test_range_rule_bounds_the_width_from_the_start():
    from datetime import datetime, timezone

    from leonaid.modules.surveys.application.disclosure import range_too_narrow

    now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
    assert not range_too_narrow(None, None, now)
    assert not range_too_narrow(None, "2026-11-04T11:00:00+00:00", now)
    assert range_too_narrow("2026-11-04T00:00:00+00:00", None, now)
    assert not range_too_narrow("2026-11-03T12:00:00+00:00", None, now)
    assert range_too_narrow(
        "2026-11-01T00:00:00+00:00", "2026-11-01T23:59:00+00:00", now
    )
    assert not range_too_narrow(
        "2026-11-01T00:00:00+00:00", "2026-11-02T00:00:00+00:00", now
    )


def test_nps_segments_follow_the_same_rules():
    counts = [1, 0, 0, 0, 0, 0, 2, 3, 3, 6, 5]  # 0..10
    nps = question("nps", "rating", counts, stats={"nps": 40.0})
    q = disclose(snapshot(20, [nps])).questions[0]
    assert q.npsSegments is not None
    # detractors 3 (withheld) -> passives 6 also withheld; promoters 11 shown
    assert (q.npsSegments.detractors, q.npsSegments.passives) == (None, None)
    assert q.npsSegments.promoters == 11
    assert q.nps == 40.0
    plain = question("r", "rating", [5, 5])
    assert disclose(snapshot(10, [plain])).questions[0].npsSegments is None
