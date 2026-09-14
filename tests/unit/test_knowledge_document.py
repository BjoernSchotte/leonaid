"""Validate real knowledge documents without transport or repository doubles."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from leonaid.modules.knowledge.api import CreatePage, UpdatePage
from leonaid.modules.knowledge.document import (
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENT_DEPTH,
    MAX_DOCUMENT_NODES,
    task_references,
    material_references,
    validate_document,
)


def document(*nodes: object) -> dict[str, object]:
    return {"type": "doc", "content": list(nodes)}


def test_supported_document_and_stable_task_references() -> None:
    task_id = str(uuid4())
    task = {"type": "taskReference", "attrs": {"taskId": task_id}}
    source = document(
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": "Vorbereitung"}],
        },
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "<script> ist Text",
                    "marks": [
                        {"type": "bold"},
                        {
                            "type": "link",
                            "attrs": {
                                "href": "https://example.org/info",
                                "target": "_blank",
                                "rel": "noopener noreferrer nofollow",
                                "class": None,
                            },
                        },
                    ],
                }
            ],
        },
        {
            "type": "orderedList",
            "attrs": {"start": 2},
            "content": [{"type": "listItem", "content": [{"type": "paragraph"}, task]}],
        },
        {
            "type": "codeBlock",
            "attrs": {"language": None},
            "content": [{"type": "text", "text": "print('hello')"}],
        },
        task,
    )
    validated = validate_document(source)
    assert validated == source
    assert task_references(validated) == {UUID(task_id)}
    source["content"] = []
    assert validated["content"]


@pytest.mark.parametrize(
    "node",
    [
        {"type": "script"},
        {"type": "text", "text": "Root text"},
        {"type": "heading", "attrs": {"level": True}},
        {"type": "heading", "attrs": {"level": 7}},
        {"type": "paragraph", "attrs": {"onclick": "bad"}},
        {"type": "paragraph", "content": [{"type": "text", "text": ""}]},
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "x", "marks": [{"type": []}]}],
        },
        {
            "type": "codeBlock",
            "content": [{"type": "text", "text": "x", "marks": [{"type": "bold"}]}],
        },
        {"type": "taskReference", "attrs": {"taskId": "not-a-uuid"}},
        {
            "type": "taskReference",
            "attrs": {"taskId": str(uuid4()), "title": "unauthorized cached title"},
        },
        {"type": "bulletList", "content": [{"type": "paragraph"}]},
        {"type": "listItem", "content": [{"type": "paragraph"}]},
        {"type": "blockquote", "content": []},
    ],
)
def test_rejects_malformed_or_unsupported_structure(node: object) -> None:
    with pytest.raises(ValueError):
        validate_document(document(node))


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "data:text/html,x",
        "file:///etc/passwd",
        "https://example.org\n/path",
        "//example.org",
        "https://",
        "https://[",
    ],
)
def test_rejects_unsafe_links(href: str) -> None:
    with pytest.raises(ValueError):
        validate_document(
            document(
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Link",
                            "marks": [{"type": "link", "attrs": {"href": href}}],
                        }
                    ],
                }
            )
        )


def test_limits_size_depth_and_node_count() -> None:
    with pytest.raises(ValueError):
        validate_document(
            document(
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "ä" * MAX_DOCUMENT_BYTES}],
                }
            )
        )
    nested: dict[str, object] = {"type": "paragraph"}
    for _ in range(MAX_DOCUMENT_DEPTH + 1):
        nested = {"type": "blockquote", "content": [nested]}
    with pytest.raises(ValueError):
        validate_document(document(nested))
    with pytest.raises(ValueError):
        validate_document(
            document(*({"type": "paragraph"} for _ in range(MAX_DOCUMENT_NODES)))
        )


def test_commands_revalidate_mutated_documents_and_strict_revisions() -> None:
    command = CreatePage.model_validate(
        {"idempotencyKey": str(uuid4()), "title": "  Planung  "}
    )
    assert command.title == "Planung"
    assert command.content == document({"type": "paragraph"})
    copied = deepcopy(command)
    copied.content["content"].append({"type": "script"})
    with pytest.raises(ValidationError):
        CreatePage.model_validate(copied)
    with pytest.raises(ValidationError):
        UpdatePage.model_validate(
            {
                "idempotencyKey": str(uuid4()),
                "expectedRevision": "1",
                "title": "Page",
                "content": command.content,
            }
        )


@pytest.mark.parametrize("style", [None, "1", "a", "A", "i", "I"])
def test_tiptap_ordered_list_attribute(style: str | None) -> None:
    source = document(
        {
            "type": "orderedList",
            "attrs": {"start": 1, "type": style},
            "content": [{"type": "listItem", "content": [{"type": "paragraph"}]}],
        }
    )
    assert validate_document(source) == source


def test_tiptap_link_title_is_bounded() -> None:
    source = document(
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "Link",
                    "marks": [
                        {
                            "type": "link",
                            "attrs": {"href": "https://example.org", "title": None},
                        }
                    ],
                }
            ],
        }
    )
    assert validate_document(source) == source
    invalid = document(
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "Link",
                    "marks": [
                        {
                            "type": "link",
                            "attrs": {
                                "href": "https://example.org",
                                "title": "x" * 2049,
                            },
                        }
                    ],
                }
            ],
        }
    )
    with pytest.raises(ValueError):
        validate_document(invalid)
    with pytest.raises(ValueError):
        validate_document(
            document(
                {
                    "type": "orderedList",
                    "attrs": {"type": "unsafe"},
                    "content": [
                        {"type": "listItem", "content": [{"type": "paragraph"}]}
                    ],
                }
            )
        )


def test_exact_material_references_are_deduplicated_without_metadata() -> None:
    material_id = uuid4()
    node = {
        "type": "materialReference",
        "attrs": {"materialId": str(material_id), "version": 1},
    }
    newer = {
        "type": "materialReference",
        "attrs": {"materialId": str(material_id), "version": 2},
    }
    validated = validate_document(
        document(node, {"type": "blockquote", "content": [node, newer]})
    )
    assert material_references(validated) == {(material_id, 1), (material_id, 2)}
    assert task_references(validated) == set()


@pytest.mark.parametrize("version", [None, True, 0, -1, "1", 1.5, 2147483648])
def test_material_reference_requires_exact_positive_integer_version(
    version: object,
) -> None:
    with pytest.raises(ValueError):
        validate_document(
            document(
                {
                    "type": "materialReference",
                    "attrs": {"materialId": str(uuid4()), "version": version},
                }
            )
        )


@pytest.mark.parametrize(
    "extra", [{"filename": "private.txt"}, {"url": "https://example.org/file"}]
)
def test_material_reference_does_not_cache_protected_metadata(
    extra: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        validate_document(
            document(
                {
                    "type": "materialReference",
                    "attrs": {"materialId": str(uuid4()), "version": 1, **extra},
                }
            )
        )


def test_material_reference_rejects_bad_id_and_children() -> None:
    for node in (
        {"type": "materialReference", "attrs": {"materialId": "invalid", "version": 1}},
        {
            "type": "materialReference",
            "attrs": {"materialId": str(uuid4()), "version": 1},
            "content": [{"type": "paragraph"}],
        },
    ):
        with pytest.raises(ValueError):
            validate_document(document(node))


def test_extended_formatting_roundtrip_keeps_old_document_valid() -> None:
    source = document(
        {
            "type": "heading",
            "attrs": {"level": 3, "textAlign": "center"},
            "content": [
                {
                    "type": "text",
                    "text": "Gestalteter Inhalt",
                    "marks": [
                        {"type": "underline"},
                        {"type": "bold"},
                        {
                            "type": "textStyle",
                            "attrs": {"fontFamily": "serif", "fontSize": "18px"},
                        },
                    ],
                }
            ],
        },
        {"type": "paragraph", "attrs": {"textAlign": None}},
    )
    assert validate_document(source) == source
    assert validate_document(document({"type": "paragraph"})) == document(
        {"type": "paragraph"}
    )


@pytest.mark.parametrize(
    "attrs",
    [
        {"fontFamily": "url(https://example.org/font)"},
        {"fontFamily": ["serif"]},
        {"fontSize": "999px"},
        {"fontSize": "18px; color:red"},
        {"color": "red"},
        {"fontSize": 18},
    ],
)
def test_font_styles_reject_unbounded_or_injected_values(attrs: object) -> None:
    with pytest.raises(ValueError):
        validate_document(
            document(
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Text",
                            "marks": [{"type": "textStyle", "attrs": attrs}],
                        }
                    ],
                }
            )
        )


@pytest.mark.parametrize(
    "attrs",
    [
        {"fontFamily": "", "fontSize": ""},
        {"fontFamily": "serif", "fontSize": ""},
        {"fontFamily": "", "fontSize": "20px"},
        {"fontFamily": None, "fontSize": ""},
    ],
)
def test_pasted_text_keeps_tiptap_unset_font_attributes(attrs: object) -> None:
    source = document(
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "Eingefügter Text",
                    "marks": [{"type": "textStyle", "attrs": attrs}],
                }
            ],
        }
    )
    assert validate_document(source) == source


@pytest.mark.parametrize("alignment", ["float", "left;position:fixed", 1, [], {}])
def test_alignment_rejects_non_contract_values(alignment: object) -> None:
    with pytest.raises(ValueError):
        validate_document(
            document({"type": "paragraph", "attrs": {"textAlign": alignment}})
        )
