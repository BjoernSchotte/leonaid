"""Bounded initial-profile definition and answer validation; no code evaluation."""

from __future__ import annotations

import json
import math
import re
from datetime import date
from typing import Any, NoReturn

from leonaid.domain.errors import DomainInvariantError

PROFILE = "initial-v1"
TYPES = {"text", "comment", "radiogroup", "dropdown", "checkbox", "rating", "matrix"}
ROOT_KEYS = {
    "title",
    "description",
    "pages",
    "showProgressBar",
    "completedHtml",
    "locale",
}
PAGE_KEYS = {"name", "title", "description", "elements", "visibleIf"}
QUESTION_KEYS = {
    "type",
    "name",
    "title",
    "description",
    "isRequired",
    "visibleIf",
    "choices",
    "rows",
    "columns",
    "isAllRowRequired",
    "inputType",
    "min",
    "max",
    "maxLength",
    "minLength",
    "rateMin",
    "rateMax",
    "rateStep",
    "minSelectedChoices",
    "maxSelectedChoices",
    "placeholder",
}
COMMON_QUESTION_KEYS = {
    "type",
    "name",
    "title",
    "description",
    "isRequired",
    "visibleIf",
}
TYPE_KEYS = {
    "text": {"inputType", "min", "max", "minLength", "maxLength", "placeholder"},
    "comment": {"minLength", "maxLength", "placeholder"},
    "radiogroup": {"choices"},
    "dropdown": {"choices", "placeholder"},
    "checkbox": {"choices", "minSelectedChoices", "maxSelectedChoices"},
    "rating": {"rateMin", "rateMax", "rateStep"},
    "matrix": {"rows", "columns", "isAllRowRequired"},
}
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,79}\Z")
LEAF = re.compile(
    r"\{([A-Za-z][A-Za-z0-9_]*)\}\s*(notempty|empty|notcontains|contains|<=|>=|!=|<>|=|<|>)\s*(.*)\Z"
)


def fail(code: str, path: str) -> NoReturn:
    raise DomainInvariantError(code, f"Ungültige Umfrageangabe: {path}")


def json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, allow_nan=False).encode())
    except (ValueError, TypeError, RecursionError):
        fail("invalid_response", "JSON")


def utf16_length(value: str) -> int:
    """Match JavaScript/native input length, including supplementary characters."""
    try:
        return len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        fail("invalid_response", "invalid Unicode scalar")


def contains_option(value: Any, allowed: list[Any]) -> bool:
    return any(
        type(value) is type(item)
        and value == item
        or type(value) in {int, float}
        and type(item) in {int, float}
        and value == item
        for item in allowed
    )


def check_properties(value: dict[str, Any]) -> None:
    for key in {"title", "description", "placeholder", "completedHtml"} & value.keys():
        if (
            not isinstance(value[key], str)
            or len(value[key]) > 10000
            or "<" in value[key]
        ):
            fail("unsupported_capability", key)
    for key in {"isRequired", "isAllRowRequired"} & value.keys():
        if type(value[key]) is not bool:
            fail("invalid_definition", key)
    for key in {
        "minLength",
        "maxLength",
        "minSelectedChoices",
        "maxSelectedChoices",
    } & value.keys():
        if type(value[key]) is not int or not 0 <= value[key] <= 10000:
            fail("invalid_definition", key)
    for key in {"min", "max", "rateMin", "rateMax", "rateStep"} & value.keys():
        if value.get("inputType") == "date" and key in {"min", "max"}:
            try:
                if date.fromisoformat(value[key]).isoformat() != value[key]:
                    raise ValueError()
            except (ValueError, TypeError):
                fail("invalid_definition", key)
        elif type(value[key]) not in {int, float} or not math.isfinite(value[key]):
            fail("invalid_definition", key)
    for lower, upper in [
        ("min", "max"),
        ("rateMin", "rateMax"),
        ("minLength", "maxLength"),
        ("minSelectedChoices", "maxSelectedChoices"),
    ]:
        if lower in value and upper in value and value[lower] > value[upper]:
            fail("invalid_definition", lower)
    if value.get("type") == "rating" and (
        value.get("rateStep", 1) <= 0
        or value.get("rateMax", 5) < value.get("rateMin", 1)
        or (value.get("rateMax", 5) - value.get("rateMin", 1))
        / value.get("rateStep", 1)
        > 99
    ):
        fail("invalid_definition", "rating")


def clauses(expression: str) -> tuple[str | None, list[str]]:
    expression = expression.strip()
    # Strip a pair only when it encloses the entire expression.
    if expression.startswith("("):
        depth, quote = 0, None
        for i, char in enumerate(expression):
            if char in {"'", '"'}:
                quote = None if quote == char else (char if quote is None else quote)
            if quote is None:
                depth += (char == "(") - (char == ")")
                if depth == 0:
                    if i == len(expression) - 1:
                        return clauses(expression[1:-1])
                    break
    for operator in (" or ", " and "):
        depth, quote, start, parts = 0, None, 0, []
        for i, char in enumerate(expression):
            if char in {"'", '"'}:
                quote = None if quote == char else (char if quote is None else quote)
            if quote is None:
                depth += (char == "(") - (char == ")")
                if depth == 0 and expression.startswith(operator, i):
                    parts.append(expression[start:i])
                    start = i + len(operator)
        if parts:
            return operator.strip(), [*parts, expression[start:]]
    return None, [expression]


def condition(expression: str, answers: dict[str, Any], preceding: set[str]) -> bool:
    if (
        not isinstance(expression, str)
        or len(expression) > 2000
        or expression.count("(") > 20
    ):
        fail("unsupported_capability", "visibleIf")
    operator, parts = clauses(expression)
    if operator:
        results = [condition(part, answers, preceding) for part in parts]
        return all(results) if operator == "and" else any(results)
    match = LEAF.fullmatch(parts[0])
    if not match or match[1] not in preceding:
        fail("unsupported_capability", "visibleIf reference or expression")
    name, op, literal = match.groups()
    value = answers.get(name)
    empty = value is None or value == "" or value == []
    if op in {"empty", "notempty"}:
        if literal:
            fail("unsupported_capability", "visibleIf empty operand")
        return empty if op == "empty" else not empty
    try:
        expected = (
            literal[1:-1]
            if re.fullmatch(r"'[^'\\]*'", literal)
            else json.loads(literal)
        )
    except (ValueError, TypeError):
        fail("unsupported_capability", "visibleIf literal")
    if (
        not isinstance(expected, (str, int, float, bool))
        or isinstance(expected, float)
        and not math.isfinite(expected)
    ):
        fail("unsupported_capability", "visibleIf literal type")
    # SurveyJS compares string expressions case-insensitively by default.
    if isinstance(value, str):
        value = value.lower()
    if isinstance(expected, str):
        expected = expected.lower()
    if isinstance(value, list):
        value = [item.lower() if isinstance(item, str) else item for item in value]
    if empty:
        return op in {"!=", "<>", "notcontains"}
    if op in {"=", "!=", "<>"}:
        equal = type(value) is type(expected) and value == expected
        if type(value) in {int, float} and type(expected) in {int, float}:
            equal = value == expected
        return equal if op == "=" else not equal
    if op in {"contains", "notcontains"}:
        found = (isinstance(value, list) and expected in value) or (
            isinstance(value, str) and isinstance(expected, str) and expected in value
        )
        return found if op == "contains" else not found
    if type(value) not in {int, float} or type(expected) not in {int, float}:
        return False
    assert isinstance(value, (int, float)) and isinstance(expected, (int, float))
    return {
        "<": value < expected,
        "<=": value <= expected,
        ">": value > expected,
        ">=": value >= expected,
    }[op]


def options(items: Any, path: str) -> list[Any]:
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        fail("invalid_definition", path)
    values = []
    for item in items:
        if isinstance(item, dict):
            if set(item) - {"value", "text"} or "value" not in item:
                fail("unsupported_capability", path)
            if "text" in item and (
                not isinstance(item["text"], str)
                or "<" in item["text"]
                or len(item["text"]) > 10000
            ):
                fail("unsupported_capability", path)
            item = item["value"]
        if (
            type(item) not in {str, int, float}
            or item in values
            or (isinstance(item, float) and not math.isfinite(item))
        ):
            fail("invalid_definition", path)
        if item == "":
            fail("invalid_definition", path)
        values.append(item)
    return values


def validate_definition(definition: Any) -> None:
    if not isinstance(definition, dict):
        fail("invalid_definition", "definition")
    if unknown := sorted(set(definition) - ROOT_KEYS):
        fail("unsupported_capability", f"definition.{unknown[0]}")
    if json_size(definition) > 262144:
        fail("limit_exceeded", "definition")
    check_properties(definition)
    if "locale" in definition and definition["locale"] not in ("de", "en", ""):
        fail("unsupported_capability", "locale")
    if "showProgressBar" in definition and definition["showProgressBar"] not in (
        "off",
        "top",
        "bottom",
        "both",
        "auto",
    ):
        fail("invalid_definition", "showProgressBar")
    pages = definition.get("pages")
    if not isinstance(pages, list) or not 1 <= len(pages) <= 25:
        fail("invalid_definition", "pages")
    preceding: set[str] = set()
    names: set[str] = set()
    for page_index, page in enumerate(pages):
        try:
            if not isinstance(page, dict) or set(page) - PAGE_KEYS:
                fail("unsupported_capability", "page")
            check_properties(page)
            name = page.get("name")
            if not isinstance(name, str) or not NAME.fullmatch(name) or name in names:
                fail("invalid_definition", "page name")
            names.add(name)
            if "visibleIf" in page:
                condition(page["visibleIf"], {}, preceding)
            elements = page.get("elements")
            if not isinstance(elements, list) or not elements:
                fail("invalid_definition", "elements")
            for question_index, question in enumerate(elements):
                try:
                    if (
                        not isinstance(question, dict)
                        or set(question) - QUESTION_KEYS
                        or not isinstance(question.get("type"), str)
                        or question.get("type") not in TYPES
                    ):
                        fail("unsupported_capability", "question")
                    kind = question["type"]
                    if set(question) - (COMMON_QUESTION_KEYS | TYPE_KEYS[kind]):
                        fail(
                            "unsupported_capability",
                            "property does not apply to question type",
                        )
                    input_type = question.get("inputType", "text")
                    if input_type not in ("text", "number", "date"):
                        fail("unsupported_capability", "inputType")
                    if kind == "text" and (
                        input_type == "text"
                        and {"min", "max"} & question.keys()
                        or input_type != "text"
                        and {"minLength", "maxLength"} & question.keys()
                    ):
                        fail(
                            "unsupported_capability", "input constraint does not apply"
                        )
                    check_properties(question)
                    name = question.get("name")
                    if (
                        not isinstance(name, str)
                        or not NAME.fullmatch(name)
                        or name in preceding
                    ):
                        fail("invalid_definition", "question name")
                    if "visibleIf" in question:
                        condition(question["visibleIf"], {}, preceding)
                    if question["type"] in {"radiogroup", "dropdown", "checkbox"}:
                        options(question.get("choices"), name)
                    if question["type"] == "matrix":
                        options(question.get("rows"), name)
                        options(question.get("columns"), name)
                    preceding.add(name)
                except DomainInvariantError as error:
                    raise DomainInvariantError(
                        error.code,
                        f"pages[{page_index}].elements[{question_index}]: {error.message}",
                    ) from error
        except DomainInvariantError as error:
            raise DomainInvariantError(
                error.code, f"pages[{page_index}]: {error.message}"
            ) from error
    if len(preceding) > 150:
        fail("limit_exceeded", "questions")


def validate_answers(
    definition: dict[str, Any], answers: Any, *, complete: bool
) -> dict[str, Any]:
    validate_definition(definition)
    if not isinstance(answers, dict) or json_size(answers) > 262144:
        fail("invalid_response", "answers")
    known = {q["name"] for p in definition["pages"] for q in p["elements"]}
    if set(answers) - known:
        fail("invalid_response", "unknown answer")
    clean: dict[str, Any] = {}
    preceding: set[str] = set()
    for page in definition["pages"]:
        page_visible = "visibleIf" not in page or condition(
            page["visibleIf"], clean, preceding
        )
        for q in page["elements"]:
            name = q["name"]
            visible = page_visible and (
                "visibleIf" not in q or condition(q["visibleIf"], clean, preceding)
            )
            preceding.add(name)
            if not visible:
                continue
            value = answers.get(name)
            if value is None or value == "" or value == []:
                if complete and (
                    q.get("isRequired")
                    or q["type"] == "checkbox"
                    and q.get("minSelectedChoices", 0) > 0
                ):
                    fail("invalid_response", name)
                continue
            kind = q["type"]
            if kind in {"text", "comment"} and q.get("inputType") not in {
                "number",
                "date",
            }:
                if not isinstance(value, str) or not q.get(
                    "minLength", 0
                ) <= utf16_length(value) <= (q.get("maxLength", 0) or 10000):
                    fail("invalid_response", name)
            elif kind == "rating" or q.get("inputType") == "number":
                low = q.get("rateMin", 1) if kind == "rating" else q.get("min", -1e12)
                high = q.get("rateMax", 5) if kind == "rating" else q.get("max", 1e12)
                if (
                    type(value) not in {int, float}
                    or not math.isfinite(value)
                    or not low <= value <= high
                ):
                    fail("invalid_response", name)
            elif q.get("inputType") == "date":
                try:
                    parsed = date.fromisoformat(value)
                    if parsed.isoformat() != value:
                        raise ValueError()
                    if (
                        q.get("min")
                        and value < q["min"]
                        or q.get("max")
                        and value > q["max"]
                    ):
                        raise ValueError()
                except (ValueError, TypeError):
                    fail("invalid_response", name)
            elif kind in {"radiogroup", "dropdown"}:
                if not contains_option(value, options(q["choices"], name)):
                    fail("invalid_response", name)
            elif kind == "checkbox":
                allowed = options(q["choices"], name)
                if (
                    not isinstance(value, list)
                    or any(not contains_option(v, allowed) for v in value)
                    or len(set(map(str, value))) != len(value)
                ):
                    fail("invalid_response", name)
                if (
                    len(value) > (q.get("maxSelectedChoices", 0) or 100)
                    or complete
                    and len(value) < q.get("minSelectedChoices", 0)
                ):
                    fail("invalid_response", name)
            elif kind == "matrix":
                rows = [str(v) for v in options(q["rows"], name)]
                cols = options(q["columns"], name)
                if (
                    not isinstance(value, dict)
                    or set(value) - set(rows)
                    or any(not contains_option(v, cols) for v in value.values())
                ):
                    fail("invalid_response", name)
                if complete and q.get("isAllRowRequired") and set(value) != set(rows):
                    fail("invalid_response", name)
            if kind == "rating" and not math.isclose(
                (value - low) / q.get("rateStep", 1),
                round((value - low) / q.get("rateStep", 1)),
            ):
                fail("invalid_response", name)
            clean[name] = value
    return clean
