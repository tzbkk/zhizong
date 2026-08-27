"""Graph-layer rules R01-R05, R17, R20: tests call rule functions directly.

Every fixture builds a Corpus by direct construction (no filesystem, no
full dispatch), so each test sees exactly one rule's output and asserts
rule_id/doc on every Violation it gets. Field names mirror the grammar's
Shapes.Document: ComponentType, Upstream/Downstream as
{structureName: [node, ...]}, lowercase `role: entrypoint`,
Parameters as {param: {Type: <structure name>}}.
"""

from zhizong.graph import (
    r01_edge_symmetry,
    r02_nodes_exist,
    r03_upstream_needs_downstream_counterpart,
    r04_structures_must_be_referenced,
    r05_entrypoint_discipline,
    r17_document_names_unique,
    r20_io_keys_resolve_to_structures,
)
from zhizong.loader import Corpus, load_corpus


def component(name: str, **overrides) -> dict:
    """Minimal shape-valid component doc; None-valued overrides are dropped."""

    doc = {
        "SchemaVersion": 1,
        "Type": "component",
        "Name": name,
        "Description": f"synthetic component {name}",
        "ComponentType": "daemon",
        "Runs": f"/usr/bin/{name}",
        "Upstream": {},
        "Downstream": {},
    }
    doc.update(overrides)
    return {key: val for key, val in doc.items() if val is not None}


def structure(name: str, **overrides) -> dict:
    """Minimal shape-valid record structure doc (scalars override Location/Definition)."""

    doc = {
        "SchemaVersion": 1,
        "Type": "structure",
        "Name": name,
        "Description": f"synthetic structure {name}",
        "Location": f"file:///data/{name}.jsonl",
        "Definition": {
            "Form": "record",
            "Table": [
                {"Field": "id", "Type": "string", "Description": "identifier"}
            ],
        },
    }
    doc.update(overrides)
    return doc


def make_corpus(*docs: dict, externals: dict | None = None, **corpus_kwargs) -> Corpus:
    kwargs = {
        "documents": {doc["Name"]: doc for doc in docs},
        "externals": externals or {},
    }
    kwargs.update(corpus_kwargs)
    return Corpus(**kwargs)


QQ_EXTERNALS = {
    "qq": {"Kind": "api", "Origin": "https://qq.example", "Description": "upstream"}
}


# ---------------------------------------------------------------- R01


def test_r01_symmetric_edges_pass():
    corpus = make_corpus(
        component("collector", Upstream={"feed": ["parser"]}),
        component("parser", Downstream={"feed": ["collector"]}),
        structure("feed"),
    )

    assert r01_edge_symmetry(corpus) == []


def test_r01_upstream_without_reciprocal_downstream_is_exactly_one_violation():
    # Spec-mandated precision case: B.Downstream[feed] EMPTY is exempt, so
    # exactly ONE violation, attributed to the declarer A, naming B.
    corpus = make_corpus(
        component("a", Upstream={"feed": ["b"]}),
        component("b", Downstream={"feed": []}),
        structure("feed"),
    )

    violations = r01_edge_symmetry(corpus)

    assert len(violations) == 1
    assert violations[0].rule_id == "R01"
    assert violations[0].doc == "a"
    assert "b" in violations[0].message
    assert violations[0].severity == "fail"


def test_r01_downstream_without_reciprocal_upstream():
    corpus = make_corpus(
        component("a", Downstream={"feed": ["b"]}),
        component("b"),
        structure("feed"),
    )

    violations = r01_edge_symmetry(corpus)

    assert len(violations) == 1
    assert violations[0].rule_id == "R01"
    assert violations[0].doc == "a"
    assert "b" in violations[0].message


def test_r01_external_nodes_exempt_from_symmetry():
    corpus = make_corpus(
        component("a", Upstream={"feed": ["external:qq"]}),
        structure("feed"),
        externals=QQ_EXTERNALS,
    )

    assert r01_edge_symmetry(corpus) == []


# ---------------------------------------------------------------- R02


def test_r02_existing_component_and_registered_external_pass():
    corpus = make_corpus(
        component("a", Upstream={"feed": ["b", "external:qq"]}),
        component("b"),
        structure("feed"),
        externals=QQ_EXTERNALS,
    )

    assert r02_nodes_exist(corpus) == []


def test_r02_unknown_component_node_fails():
    corpus = make_corpus(
        component("a", Upstream={"feed": ["ghost"]}),
        structure("feed"),
    )

    violations = r02_nodes_exist(corpus)

    assert len(violations) == 1
    assert violations[0].rule_id == "R02"
    assert violations[0].doc == "a"
    assert "ghost" in violations[0].message


def test_r02_unregistered_external_source_fails():
    corpus = make_corpus(
        component("a", Downstream={"feed": ["external:nowhere"]}),
        structure("feed"),
        externals=QQ_EXTERNALS,
    )

    violations = r02_nodes_exist(corpus)

    assert len(violations) == 1
    assert violations[0].rule_id == "R02"
    assert violations[0].doc == "a"
    assert "nowhere" in violations[0].message


# ---------------------------------------------------------------- R03


def test_r03_reciprocal_downstream_holder_pass():
    corpus = make_corpus(
        component("a", Upstream={"feed": ["b"]}),
        component("b", Downstream={"feed": ["a"]}),
        structure("feed"),
    )

    assert r03_upstream_needs_downstream_counterpart(corpus) == []


def test_r03_empty_upstream_list_is_legal():
    # Empty list means the counterparty is the file itself — no X needed.
    corpus = make_corpus(
        component("a", Upstream={"feed": []}),
        structure("feed"),
    )

    assert r03_upstream_needs_downstream_counterpart(corpus) == []


def test_r03_nonempty_upstream_without_downstream_holder_fails():
    corpus = make_corpus(
        component("a", Upstream={"feed": ["b"]}),
        component("b", Downstream={}),
        structure("feed"),
    )

    violations = r03_upstream_needs_downstream_counterpart(corpus)

    assert len(violations) == 1
    assert violations[0].rule_id == "R03"
    assert violations[0].doc == "a"
    assert "feed" in violations[0].message


def test_r03_pure_external_upstream_exempt():
    # External sources declare no Downstream — pure external lists need
    # no endorsement.
    corpus = make_corpus(
        component("a", Upstream={"feed": ["external:qq"]}),
        structure("feed"),
        externals=QQ_EXTERNALS,
    )

    assert r03_upstream_needs_downstream_counterpart(corpus) == []


def test_r03_mixed_upstream_without_endorsement_fails():
    corpus = make_corpus(
        component("a", Upstream={"feed": ["external:qq", "b"]}),
        component("b", Downstream={}),
        structure("feed"),
        externals=QQ_EXTERNALS,
    )

    violations = r03_upstream_needs_downstream_counterpart(corpus)

    assert len(violations) == 1
    assert violations[0].rule_id == "R03"
    assert violations[0].doc == "a"
    assert "feed" in violations[0].message


def test_r03_mixed_upstream_with_endorsement_passes():
    corpus = make_corpus(
        component("a", Upstream={"feed": ["external:qq", "b"]}),
        component("b", Downstream={"feed": ["a"]}),
        structure("feed"),
        externals=QQ_EXTERNALS,
    )

    assert r03_upstream_needs_downstream_counterpart(corpus) == []


# ---------------------------------------------------------------- R04


def test_r04_io_key_and_scalar_param_references_pass():
    # "feed" is referenced as an I/O key; scalar "price" is referenced
    # ONLY via feed's Parameters.Type — that is the scalar exemption.
    corpus = make_corpus(
        component("a", Upstream={"feed": []}),
        structure(
            "feed",
            Parameters={"price": {"Type": "price"}},
        ),
        structure(
            "price",
            Location="urn:demo:type:price",
            Definition={
                "Form": "scalar",
                "Base": "number",
                "Pattern": r"^\d+(\.\d+)?$",
            },
        ),
    )

    assert r04_structures_must_be_referenced(corpus) == []


def test_r04_unreferenced_structure_fails():
    corpus = make_corpus(
        component("a", Upstream={"feed": []}),
        structure("feed"),
        structure("lonely"),
    )

    violations = r04_structures_must_be_referenced(corpus)

    assert len(violations) == 1
    assert violations[0].rule_id == "R04"
    assert violations[0].doc == "lonely"
    assert "lonely" in violations[0].message


# ---------------------------------------------------------------- R05


def test_r05_entrypoint_marking_and_edged_component_pass():
    corpus = make_corpus(
        component("boot", role="entrypoint"),
        component(
            "worker",
            Downstream={"feed": ["boot"]},
        ),
        structure("feed"),
    )

    assert r05_entrypoint_discipline(corpus) == []


def test_r05_edgeless_without_entrypoint_role_fails():
    corpus = make_corpus(component("adrift", Upstream={}, Downstream={}))

    violations = r05_entrypoint_discipline(corpus)

    assert len(violations) == 1
    assert violations[0].rule_id == "R05"
    assert violations[0].doc == "adrift"
    assert "entrypoint" in violations[0].message


def test_r05_library_must_not_be_marked_entrypoint():
    corpus = make_corpus(
        component(
            "libx",
            ComponentType="library",
            Runs=None,
            role="entrypoint",
            Upstream={"feed": ["helper"]},
        ),
        component("helper", Downstream={"feed": ["libx"]}),
        structure("feed"),
    )

    violations = r05_entrypoint_discipline(corpus)

    assert len(violations) == 1
    assert violations[0].rule_id == "R05"
    assert violations[0].doc == "libx"
    assert "library" in violations[0].message


def test_r05_empty_node_lists_count_as_edgeless():
    # Lists present but ALL empty still means no edges (file counterparties).
    corpus = make_corpus(component("filesonly", Upstream={"feed": []}))

    violations = r05_entrypoint_discipline(corpus)

    assert len(violations) == 1
    assert violations[0].rule_id == "R05"
    assert violations[0].doc == "filesonly"


# ---------------------------------------------------------------- R17


def test_r17_no_duplicate_names_pass():
    corpus = make_corpus(component("a"), structure("feed"))

    assert r17_document_names_unique(corpus) == []


def test_r17_duplicate_names_each_flagged():
    corpus = make_corpus(
        component("a"),
        duplicate_names=["dup", "dup"],
    )

    violations = r17_document_names_unique(corpus)

    assert len(violations) == 2
    assert {v.rule_id for v in violations} == {"R17"}
    assert {v.doc for v in violations} == {"dup"}
    assert all("dup" in v.message for v in violations)
    assert all(v.severity == "fail" for v in violations)


# ---------------------------------------------------------------- R20


def test_r20_resolvable_io_keys_pass():
    corpus = make_corpus(
        component("a", Upstream={"feed": []}, Downstream={"events": ["b"]}),
        component("b", Upstream={"events": ["a"]}),
        structure("feed"),
        structure("events"),
    )

    assert r20_io_keys_resolve_to_structures(corpus) == []


def test_r20_unresolvable_io_key_fails():
    corpus = make_corpus(
        component("a", Upstream={"ghost": []}),
        structure("feed"),
    )

    violations = r20_io_keys_resolve_to_structures(corpus)

    assert len(violations) == 1
    assert violations[0].rule_id == "R20"
    assert violations[0].doc == "a"
    assert "ghost" in violations[0].message


# ------------------------------------------------- loader enabler (R17)


def test_loader_records_duplicate_names_first_wins(tmp_path):
    (tmp_path / "first.yaml").write_text(
        "SchemaVersion: 1\nType: component\nName: dup\n"
        "Description: first\nComponentType: daemon\nRuns: /bin/first\n"
        "Upstream: {}\nDownstream: {}\n",
        encoding="utf-8",
    )
    (tmp_path / "second.yaml").write_text(
        "SchemaVersion: 1\nType: component\nName: dup\n"
        "Description: second\nComponentType: cli\nRuns: /bin/second\n"
        "Upstream: {}\nDownstream: {}\n",
        encoding="utf-8",
    )

    corpus = load_corpus(tmp_path)

    assert corpus.duplicate_names == ["dup"]
    assert corpus.documents["dup"]["Description"] == "first"
    violations = r17_document_names_unique(corpus)
    assert len(violations) == 1
    assert violations[0].rule_id == "R17"
    assert violations[0].doc == "dup"
