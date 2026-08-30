"""Shapes layer tests: JSON Schema validation + R16/R19 invariant checks."""

import importlib.resources

import pytest
import yaml

from zhizong import shapes
from zhizong.loader import Corpus


def system_doc() -> dict:
    with (importlib.resources.files("zhizong") / "versions" / "1.yaml").open(
        "r", encoding="utf-8"
    ) as f:
        return yaml.safe_load(f)


def make_corpus(*docs, system_names=frozenset({1})) -> Corpus:
    return Corpus(
        documents={d["Name"]: d for d in docs},
        externals={},
        violations=[],
        system_names=system_names,
    )


def base_structure(name="s1") -> dict:
    return {
        "SchemaVersion": 1,
        "Type": "structure",
        "Name": name,
        "Description": "a structure",
        "Location": "file://data/s1.dat",
        "Definition": {
            "Form": "record",
            "Table": [{"Field": "a", "Type": "string", "Description": "field a"}],
        },
    }


def base_component(name="c1") -> dict:
    return {
        "SchemaVersion": 1,
        "Type": "component",
        "Name": name,
        "Description": "a component",
        "ComponentType": "daemon",
        "Upstream": {},
        "Downstream": {},
        "Runs": "./run.sh",
    }


def test_valid_corpus_passes_all_layers():
    corpus = make_corpus(system_doc(), base_structure(), base_component())

    assert shapes.validate_shapes(corpus) == []
    assert shapes.r16_schema_version_matches_version_doc(corpus) == []
    assert shapes.r19_version_docs_self_validate(corpus) == []


def test_shape_violating_document_rejected():
    bad = base_structure()
    bad["Bogus"] = True
    corpus = make_corpus(system_doc(), bad)

    violations = shapes.validate_shapes(corpus)

    assert len(violations) == 1
    v = violations[0]
    assert v.rule_id == "Shapes.Document"
    assert v.doc == "s1"
    assert v.severity == "fail"
    assert "Bogus" in v.message


def test_schema_version_2_rejected_by_r16_but_shape_valid():
    doc = base_structure()
    doc["SchemaVersion"] = 2
    corpus = make_corpus(system_doc(), doc)

    assert shapes.validate_shapes(corpus) == []

    r16 = shapes.r16_schema_version_matches_version_doc(corpus)
    assert len(r16) == 1
    assert r16[0].rule_id == "R16"
    assert r16[0].doc == "s1"
    assert r16[0].severity == "fail"
    assert "2" in r16[0].message


def test_missing_schema_version_rejected_by_shapes_not_by_r16():
    doc = base_structure()
    del doc["SchemaVersion"]
    corpus = make_corpus(system_doc(), doc)

    shape_violations = shapes.validate_shapes(corpus)
    assert any(
        v.doc == "s1" and "SchemaVersion" in v.message for v in shape_violations
    )

    assert shapes.r16_schema_version_matches_version_doc(corpus) == []


def test_r19_detects_non_self_validating_version_document():
    bogus = {
        "SchemaVersion": 1,
        "Type": "version",
        "Name": 2,
        "Description": "broken grammar",
        "Definition": {
            "Shapes": {
                "Document": {
                    "type": "object",
                    "required": ["Ghost"],
                    "properties": {},
                    "additionalProperties": False,
                }
            }
        },
    }
    corpus = make_corpus(system_doc(), bogus)

    r19 = shapes.r19_version_docs_self_validate(corpus)

    assert r19
    assert all(v.rule_id == "R19" and v.doc == 2 for v in r19)
    assert [v for v in r19 if v.doc == 1] == []


def test_r19_missing_shapes_document_is_a_violation():
    bogus = {
        "SchemaVersion": 1,
        "Type": "version",
        "Name": 2,
        "Description": "no shapes",
        "Definition": {},
    }
    corpus = make_corpus(system_doc(), bogus)

    r19 = shapes.r19_version_docs_self_validate(corpus)

    assert len(r19) == 1
    assert r19[0].doc == 2
    assert "Shapes.Document" in r19[0].message


def test_validate_shapes_requires_injected_system_grammar():
    corpus = make_corpus(base_structure(), system_names=frozenset())

    with pytest.raises(RuntimeError):
        shapes.validate_shapes(corpus)


# --------------------------- generation-2 grammar: directives, Location, Provides


def test_shape_directive_value_accepted_in_io_map():
    doc = base_component()
    doc["Upstream"] = {"Job": "GET /archive/jobs/{id}"}
    corpus = make_corpus(system_doc(), base_structure(), doc)

    assert shapes.validate_shapes(corpus) == []


def test_shape_lowercase_verb_string_rejected():
    doc = base_component()
    doc["Upstream"] = {"Job": "get /archive/jobs"}
    corpus = make_corpus(system_doc(), base_structure(), doc)

    assert shapes.validate_shapes(corpus) != []


def test_shape_query_string_in_directive_rejected():
    doc = base_component()
    doc["Upstream"] = {"Logs": "GET /targets/x/logs?tail=5"}
    corpus = make_corpus(system_doc(), base_structure(), doc)

    assert shapes.validate_shapes(corpus) != []


def test_shape_structure_without_location_accepted():
    doc = base_structure()
    del doc["Location"]

    assert shapes.validate_shapes(make_corpus(system_doc(), doc, base_component())) == []


def test_shape_http_location_rejected():
    doc = base_structure()
    doc["Location"] = "http://127.0.0.1:9420/api/feed"

    assert shapes.validate_shapes(make_corpus(system_doc(), doc, base_component())) != []


def test_shape_service_requires_binds_only():
    doc = base_component()
    doc.update({"ComponentType": "service", "Binds": "127.0.0.1:9420"})

    assert shapes.validate_shapes(make_corpus(system_doc(), base_structure(), doc)) == []


def test_shape_provides_field_rejected():
    doc = base_component()
    doc.update({"ComponentType": "service", "Binds": "127.0.0.1:9420"})
    doc["Provides"] = "routes/svc.txt"

    assert shapes.validate_shapes(make_corpus(system_doc(), base_structure(), doc)) != []


def test_shape_non_service_binds_rejected():
    doc = base_component()
    doc["Binds"] = "127.0.0.1:9420"

    assert shapes.validate_shapes(make_corpus(system_doc(), base_structure(), doc)) != []
