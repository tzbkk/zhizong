"""Loader tests: discovery, parse, externals, system injection, name collisions."""

import importlib.resources

import yaml

from zhizong.loader import load_corpus


def system_doc() -> dict:
    with (importlib.resources.files("zhizong") / "versions" / "1.yaml").open(
        "r", encoding="utf-8"
    ) as f:
        return yaml.safe_load(f)


def write(path, text) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


STRUCTURE_YAML = """\
SchemaVersion: 1
Type: structure
Name: feeds
Description: feed records
Location: file://data/feeds.jsonl
Parameters:
  guild:
    Type: string
Definition:
  Form: record
  Table:
    - Field: id
      Type: string
      Description: record id
"""

COMPONENT_YAML = """\
SchemaVersion: 1
Type: component
Name: scraper
Description: web scraper
ComponentType: daemon
Upstream: {}
Downstream:
  feeds: [scraper]
Runs: python -m src.web_scraper
"""


def test_discovery_and_parse(tmp_path):
    contracts = tmp_path / "contracts"
    write(contracts / "feeds.yaml", STRUCTURE_YAML)
    write(contracts / "scraper.yaml", COMPONENT_YAML)

    corpus = load_corpus(contracts)

    assert set(corpus.structures()) == {"feeds"}
    assert set(corpus.components()) == {"scraper"}
    assert set(corpus.versions()) == {1}
    assert corpus.documents["feeds"]["Type"] == "structure"
    assert corpus.documents["scraper"]["ComponentType"] == "daemon"
    assert corpus.externals == {}
    assert corpus.violations == []


def test_externals_loaded_not_a_document(tmp_path):
    contracts = tmp_path / "contracts"
    write(
        contracts / "externals.yaml",
        "qq_api:\n"
        "  Kind: http\n"
        "  Origin: https://example.com\n"
        "  Description: upstream source\n",
    )
    write(
        contracts / "sub" / "externals.yaml",
        "SchemaVersion: 1\n"
        "Type: structure\n"
        "Name: nested\n"
        "Description: nested doc\n"
        "Location: urn:zhizong:nested\n"
        "Definition:\n"
        "  Form: scalar\n"
        "  Base: string\n"
        "  Pattern: ^a+$\n",
    )

    corpus = load_corpus(contracts)

    assert corpus.externals == {
        "qq_api": {
            "Kind": "http",
            "Origin": "https://example.com",
            "Description": "upstream source",
        }
    }
    assert "qq_api" not in corpus.documents
    assert "nested" in corpus.documents


def test_missing_root_yields_corpus_with_only_system_documents(tmp_path):
    corpus = load_corpus(tmp_path / "does-not-exist")

    assert corpus.externals == {}
    assert corpus.violations == []
    assert set(corpus.documents) == {1}
    assert corpus.documents[1] == system_doc()


def test_system_injection(tmp_path):
    corpus = load_corpus(tmp_path)

    assert corpus.system_names == {1}
    assert corpus.documents == {1: system_doc()}
    assert corpus.violations == []
    latest = corpus.latest_system_version()
    assert latest is corpus.documents[1]
    assert latest is not None
    assert latest["Type"] == "version"
    schema = latest["Definition"]["Shapes"]["Document"]
    assert schema["required"] == ["SchemaVersion", "Type", "Name", "Description"]


def test_same_name_as_system_document_refused_not_overwritten(tmp_path):
    contracts = tmp_path / "contracts"
    write(
        contracts / "fake-grammar.yaml",
        "SchemaVersion: 1\n"
        "Type: version\n"
        "Name: 1\n"
        "Description: counterfeit grammar\n"
        "Definition: {}\n",
    )

    corpus = load_corpus(contracts)

    r17 = [v for v in corpus.violations if v.rule_id == "R17"]
    assert len(r17) == 1
    assert r17[0].doc == 1
    assert r17[0].severity == "fail"
    assert corpus.documents[1] == system_doc()
    assert corpus.documents[1]["Description"] != "counterfeit grammar"


def test_nameless_document_is_a_violation_not_a_crash(tmp_path):
    contracts = tmp_path / "contracts"
    write(contracts / "no-name.yaml", "Description: a document without a Name\n")

    corpus = load_corpus(contracts)

    assert len(corpus.violations) == 1
    v = corpus.violations[0]
    assert v.rule_id == "Shapes.Document"
    assert v.doc is None
    assert v.severity == "fail"
    assert "no-name.yaml" in v.message
    assert set(corpus.documents) == {1}


def test_unparseable_yaml_is_a_violation_not_a_crash(tmp_path):
    contracts = tmp_path / "contracts"
    write(contracts / "broken.yaml", "foo: [unclosed\n")

    corpus = load_corpus(contracts)

    assert len(corpus.violations) == 1
    v = corpus.violations[0]
    assert v.rule_id == "Shapes.Document"
    assert v.doc is None
    assert v.severity == "fail"
    assert "broken.yaml" in v.message
    assert set(corpus.documents) == {1}
