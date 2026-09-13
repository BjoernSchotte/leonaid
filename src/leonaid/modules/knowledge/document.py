"""Bounded Tiptap document subset for the initial knowledge editor."""

import json
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

MAX_DOCUMENT_BYTES = 1048576
MAX_DOCUMENT_NODES = 10000
MAX_DOCUMENT_DEPTH = 32
BLOCKS = {
    "paragraph",
    "heading",
    "bulletList",
    "orderedList",
    "blockquote",
    "codeBlock",
    "horizontalRule",
    "taskReference",
}
INLINE = {"text", "hardBreak"}


def validate_document(value: object) -> dict[str, Any]:
    """Validate JSON before persistence; object access is checked by the service."""
    if not isinstance(value, dict) or value.get("type") != "doc":
        raise ValueError("Ein Tiptap-Dokument mit doc-Wurzel ist erforderlich.")
    stack: list[tuple[object, int, set[str]]] = [(value, 0, {"doc"})]
    count = 0
    while stack:
        node, depth, allowed = stack.pop()
        count += 1
        if depth > MAX_DOCUMENT_DEPTH or count > MAX_DOCUMENT_NODES:
            raise ValueError(
                "Das Dokument ist zu tief verschachtelt oder enthält zu viele Elemente."
            )
        if not isinstance(node, dict) or set(node) - {
            "type",
            "attrs",
            "content",
            "text",
            "marks",
        }:
            raise ValueError("Ungültiger Dokumentknoten.")
        kind = node.get("type")
        if not isinstance(kind, str) or kind not in allowed:
            raise ValueError("Dieser Dokumentknoten ist hier nicht erlaubt.")
        attrs = node.get("attrs", {})
        if not isinstance(attrs, dict):
            raise ValueError("Ungültige Dokumentattribute.")
        if kind == "heading":
            if (
                set(attrs) != {"level"}
                or type(attrs["level"]) is not int
                or not 1 <= attrs["level"] <= 6
            ):
                raise ValueError("Ungültige Überschriftenebene.")
        elif kind == "orderedList":
            if (
                set(attrs) - {"start"}
                or type(attrs.get("start", 1)) is not int
                or not 1 <= attrs.get("start", 1) <= 2147483647
            ):
                raise ValueError("Ungültiger Listenbeginn.")
        elif kind == "codeBlock":
            language = attrs.get("language")
            if set(attrs) - {"language"} or (
                language is not None
                and (not isinstance(language, str) or len(language) > 64)
            ):
                raise ValueError("Ungültige Codeblock-Attribute.")
        elif kind == "taskReference":
            if set(attrs) != {"taskId"} or not isinstance(attrs["taskId"], str):
                raise ValueError("Eine stabile Task-ID ist erforderlich.")
            UUID(attrs["taskId"])
        elif attrs:
            raise ValueError("Dieser Knoten unterstützt keine Attribute.")
        marks = node.get("marks", [])
        if not isinstance(marks, list) or (marks and kind != "text") or len(marks) > 5:
            raise ValueError("Ungültige Textformatierung.")
        for mark in marks:
            validate_mark(mark)
        if kind == "text":
            if (
                not isinstance(node.get("text"), str)
                or not node["text"]
                or len(node["text"]) > MAX_DOCUMENT_BYTES
                or "content" in node
            ):
                raise ValueError("Ein Textknoten benötigt Text ohne Unterknoten.")
            continue
        if "text" in node:
            raise ValueError("Text ist nur in Textknoten erlaubt.")
        children = node.get("content", [])
        if not isinstance(children, list):
            raise ValueError("content muss eine Liste sein.")
        if kind in {"hardBreak", "horizontalRule", "taskReference"}:
            if children:
                raise ValueError("Dieser Knoten besitzt keinen Inhalt.")
            continue
        if (
            kind in {"doc", "blockquote", "bulletList", "orderedList", "listItem"}
            and not children
        ):
            raise ValueError("Dieser Knoten benötigt Inhalt.")
        if kind == "listItem" and (
            not isinstance(children[0], dict) or children[0].get("type") != "paragraph"
        ):
            raise ValueError("Listeneinträge beginnen mit einem Absatz.")
        permitted = (
            INLINE
            if kind in {"paragraph", "heading"}
            else {"text"}
            if kind == "codeBlock"
            else {"listItem"}
            if kind in {"bulletList", "orderedList"}
            else BLOCKS
        )
        if kind == "codeBlock" and any(
            isinstance(child, dict) and child.get("marks") for child in children
        ):
            raise ValueError("Codeblöcke enthalten unformatierten Text.")
        if count + len(stack) + len(children) > MAX_DOCUMENT_NODES:
            raise ValueError("Das Dokument enthält zu viele Elemente.")
        stack.extend((child, depth + 1, permitted) for child in children)
    # Copy into plain JSON so caller mutations cannot alter a validated snapshot.
    try:
        serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(serialized.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise ValueError("Das Dokument ist größer als 1 MiB.")
        return dict(json.loads(serialized))
    except (TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("Das Dokument enthält ungültige JSON-Daten.") from error


def validate_mark(mark: object) -> None:
    if not isinstance(mark, dict) or set(mark) - {"type", "attrs"}:
        raise ValueError("Ungültige Textformatierung.")
    kind = mark.get("type")
    if not isinstance(kind, str):
        raise ValueError("Ungültiger Formattyp.")
    attrs = mark.get("attrs", {})
    if not isinstance(attrs, dict):
        raise ValueError("Ungültige Formatattribute.")
    if kind in {"bold", "italic", "strike", "code"} and not attrs:
        return
    if kind != "link" or set(attrs) - {"href", "target", "rel", "class"}:
        raise ValueError("Diese Textformatierung wird nicht unterstützt.")
    href = attrs.get("href")
    if (
        not isinstance(href, str)
        or len(href) > 2048
        or any(ord(char) < 32 or ord(char) == 127 for char in href)
    ):
        raise ValueError("Ungültiger Link.")
    url = urlsplit(href)
    if url.scheme not in {"https", "http"} or not url.hostname:
        raise ValueError("Links benötigen eine vollständige HTTP- oder HTTPS-Adresse.")
    if (
        attrs.get("target") not in (None, "_blank", "_self")
        or attrs.get("class") is not None
    ):
        raise ValueError("Ungültige Linkattribute.")
    rel = attrs.get("rel")
    if rel is not None and (
        not isinstance(rel, str)
        or len(rel) > 128
        or set(rel.split()) - {"noopener", "noreferrer", "nofollow"}
    ):
        raise ValueError("Ungültige Linkbeziehung.")


def task_references(document: dict[str, Any]) -> set[UUID]:
    """Extract IDs from an already validated document, without granting access."""
    result: set[UUID] = set()
    stack = [document]
    while stack:
        node = stack.pop()
        if node["type"] == "taskReference":
            result.add(UUID(node["attrs"]["taskId"]))
        stack.extend(node.get("content", []))
    return result
