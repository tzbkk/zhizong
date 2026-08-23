"""Compiler tests: one per Semantics.FieldTableCompilation rule (8 rules).

The exact expected schema dicts below lock the normative mapping shipped in
``zhizong/versions/1.yaml`` (Semantics.FieldTableCompilation.Rules).
"""

import copy

import jsonschema
import pytest

from zhizong.compile import compile_structure
from zhizong.loader import Corpus


def structure(name: str, table=None, form: str = "record", **definition_extra) -> dict:
    definition: dict = {"Form": form}
    if table is not None:
        definition["Table"] = table
    definition.update(definition_extra)
    return {
        "SchemaVersion": 1,
        "Type": "structure",
        "Name": name,
        "Description": f"{name} structure",
        "Location": f"file://data/{name}.dat",
        "Definition": definition,
    }


def scalar(name: str, base: str, pattern: str) -> dict:
    return {
        "SchemaVersion": 1,
        "Type": "structure",
        "Name": name,
        "Description": f"{name} scalar",
        "Location": f"urn:demo:type:{name}",
        "Definition": {"Form": "scalar", "Base": base, "Pattern": pattern},
    }


def item(field: str, type_: str, required=None, fields=None) -> dict:
    entry = {"Field": field, "Type": type_, "Description": f"field {field}"}
    if required is not None:
        entry["Required"] = required
    if fields is not None:
        entry["Fields"] = fields
    return entry


def corpus_of(*docs: dict) -> Corpus:
    return Corpus(
        documents={d["Name"]: d for d in docs},
        externals={},
        violations=[],
        system_names=frozenset(),
    )


def test_rule1_base_types_map_directly():
    doc = structure(
        "Rec",
        [
            item("s", "string"),
            item("i", "integer"),
            item("n", "number"),
            item("b", "boolean"),
        ],
    )

    assert compile_structure(doc, corpus_of(doc)) == {
        "type": "object",
        "properties": {
            "s": {"type": "string"},
            "i": {"type": "integer"},
            "n": {"type": "number"},
            "b": {"type": "boolean"},
        },
        "required": [],
        "additionalProperties": True,
        "$defs": {},
    }


def test_rule2_object_with_fields_compiles_nested():
    doc = structure(
        "Rec",
        [
            item("title", "object", fields=[item("poster", "string", required=True)]),
            item("meta", "object", fields=[item("note", "string")]),
        ],
    )

    assert compile_structure(doc, corpus_of(doc)) == {
        "type": "object",
        "properties": {
            "title": {
                "type": "object",
                "properties": {"poster": {"type": "string"}},
                "required": ["poster"],
                "additionalProperties": True,
            },
            "meta": {
                "type": "object",
                "properties": {"note": {"type": "string"}},
                "additionalProperties": True,
            },
        },
        "required": [],
        "additionalProperties": True,
        "$defs": {},
    }


def _all_additional_properties_values(node):
    if isinstance(node, dict):
        if "additionalProperties" in node:
            yield node["additionalProperties"]
        for value in node.values():
            yield from _all_additional_properties_values(value)
    elif isinstance(node, list):
        for value in node:
            yield from _all_additional_properties_values(value)


def test_rule3_additional_properties_always_true_never_false():
    doc = structure(
        "Rec",
        [
            item("title", "object", fields=[item("poster", "string")]),
            item("opaque", "object"),
        ],
    )
    schema = compile_structure(doc, corpus_of(doc))

    values = list(_all_additional_properties_values(schema))
    assert values  # root and nested object levels declare it explicitly
    assert all(value is True for value in values)

    validator = jsonschema.Draft202012Validator(schema)
    # unknown upstream fields are legal at every object level
    assert validator.is_valid({"unknownTop": 1, "title": {"poster": "p", "extra": 2}})


def test_rule4_object_without_fields_is_opaque():
    doc = structure("Rec", [item("meta", "object")])

    assert compile_structure(doc, corpus_of(doc))["properties"]["meta"] == {
        "type": "object"
    }


def test_rule5_array_items_compile_inner_type():
    doc = structure(
        "Rec",
        [
            item("tags", "array<string>"),
            item("matrix", "array<array<number>>"),
            item("thumbs", "array<object>", fields=[item("poster", "string")]),
        ],
    )
    schema = compile_structure(doc, corpus_of(doc))

    assert schema["properties"]["tags"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert schema["properties"]["matrix"] == {
        "type": "array",
        "items": {"type": "array", "items": {"type": "number"}},
    }
    assert schema["properties"]["thumbs"] == {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"poster": {"type": "string"}},
            "additionalProperties": True,
        },
    }


def test_rule6_required_true_enters_required_list_absent_is_optional():
    doc = structure(
        "Rec",
        [
            item("id", "string", required=True),
            item("off", "string", required=False),
            item("opt", "string"),
        ],
    )
    schema = compile_structure(doc, corpus_of(doc))

    assert schema["required"] == ["id"]


def test_rule7_scalar_reference_uses_base_and_pattern():
    sid = scalar("FeedId", "string", "^feed-[0-9]+$")
    doc = structure("Rec", [item("id", "FeedId", required=True)])
    schema = compile_structure(doc, corpus_of(sid, doc))

    assert schema["properties"]["id"] == {"type": "string", "pattern": "^feed-[0-9]+$"}

    validator = jsonschema.Draft202012Validator(schema)
    assert validator.is_valid({"id": "feed-42"})
    assert not validator.is_valid({"id": "not-a-feed"})
    assert not validator.is_valid({"id": 7})


def test_rule8_record_reference_injected_via_defs_ref():
    image = structure(
        "ImageRecord",
        [item("url", "string", required=True), item("width", "integer")],
    )
    feed = structure(
        "FeedRecord",
        [item("id", "string", required=True), item("images", "array<ImageRecord>")],
    )
    schema = compile_structure(feed, corpus_of(image, feed))

    assert schema["$defs"] == {
        "ImageRecord": {
            "type": "object",
            "properties": {"url": {"type": "string"}, "width": {"type": "integer"}},
            "required": ["url"],
            "additionalProperties": True,
        }
    }
    assert schema["properties"]["images"] == {
        "type": "array",
        "items": {"$ref": "#/$defs/ImageRecord"},
    }

    # the $ref must actually enforce the referenced record's constraints
    validator = jsonschema.Draft202012Validator(schema)
    assert validator.is_valid({"id": "f1", "images": [{"url": "u", "width": 3}]})
    assert validator.is_valid({"id": "f1", "images": [{"url": "u"}]})
    assert not validator.is_valid({"id": "f1", "images": [{"width": 3}]})


def test_rule8_nested_record_dependencies_compiled_recursively():
    media = structure("MediaRecord", [item("kind", "string")])
    image = structure("ImageRecord", [item("media", "MediaRecord", required=True)])
    feed = structure("FeedRecord", [item("cover", "ImageRecord")])
    schema = compile_structure(feed, corpus_of(media, image, feed))

    assert schema["properties"]["cover"] == {"$ref": "#/$defs/ImageRecord"}
    assert set(schema["$defs"]) == {"ImageRecord", "MediaRecord"}
    assert schema["$defs"]["ImageRecord"]["properties"]["media"] == {
        "$ref": "#/$defs/MediaRecord"
    }

    validator = jsonschema.Draft202012Validator(schema)
    assert validator.is_valid({"cover": {"media": {"kind": "photo", "extra": 1}}})
    assert not validator.is_valid({"cover": {}})  # media is required in ImageRecord


def test_repeated_record_reference_compiles_once_into_defs():
    image = structure("ImageRecord", [item("url", "string")])
    feed = structure(
        "FeedRecord", [item("a", "ImageRecord"), item("b", "ImageRecord")]
    )
    schema = compile_structure(feed, corpus_of(image, feed))

    assert set(schema["$defs"]) == {"ImageRecord"}
    assert schema["properties"]["a"] == schema["properties"]["b"] == {
        "$ref": "#/$defs/ImageRecord"
    }


def test_record_reference_cycle_raises_clear_error():
    a = structure("A", [item("b", "B")])
    b = structure("B", [item("a", "A")])

    with pytest.raises(ValueError, match="cycle.*A -> B -> A"):
        compile_structure(a, corpus_of(a, b))


def test_self_reference_raises_clear_error():
    a = structure("A", [item("a", "A")])

    with pytest.raises(ValueError, match="cycle.*A -> A"):
        compile_structure(a, corpus_of(a))


def test_unknown_structure_reference_raises_clear_error():
    doc = structure("Rec", [item("x", "Ghost")])

    with pytest.raises(ValueError, match="Ghost"):
        compile_structure(doc, corpus_of(doc))


def test_grammar_reference_in_field_table_raises():
    grammar = structure("LogLine", form="grammar")
    grammar["Definition"]["Productions"] = "line ::= /.+/"
    doc = structure("Rec", [item("line", "LogLine")])

    with pytest.raises(ValueError, match="grammar"):
        compile_structure(doc, corpus_of(grammar, doc))


def test_non_record_structure_cannot_compile():
    doc = structure("G", form="grammar")
    doc["Definition"]["Productions"] = "line ::= /.+/"

    with pytest.raises(ValueError, match="record"):
        compile_structure(doc, corpus_of(doc))


def test_compilation_deterministic_and_corpus_untouched():
    image = structure("ImageRecord", [item("url", "string", required=True)])
    feed = structure("FeedRecord", [item("images", "array<ImageRecord>")])
    corpus = corpus_of(image, feed)
    before = copy.deepcopy(corpus.documents)

    first = compile_structure(feed, corpus)
    second = compile_structure(feed, corpus)

    assert first == second
    assert corpus.documents == before
