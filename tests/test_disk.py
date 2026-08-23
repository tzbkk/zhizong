"""Disk-tree rule tests: R11 fixture tree (bidirectional), R12 real tree.

Direct-construction corpora (no filesystem loading): the trees live under
``tmp_path`` and are wired in via ``configure_disk``.
"""

from pathlib import Path

import pytest

import zhizong.disk
from zhizong.disk import (
    configure_disk,
    r11_fixture_tree_bidirectional,
    r12_real_tree_matches,
)
from zhizong.loader import Corpus


def structure(name, location, **extra):
    doc = {
        "SchemaVersion": 1,
        "Type": "structure",
        "Name": name,
        "Description": f"{name} records",
        "Location": location,
        "Definition": {
            "Form": "record",
            "Table": [
                {"Field": "id", "Type": "string", "Description": "record id"}
            ],
        },
    }
    doc.update(extra)
    return doc


def corpus_of(*docs):
    return Corpus(documents={d["Name"]: d for d in docs})


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


FEED = "file:data/{guild}/feeds.jsonl"


# --- R11: fixture tree, bidirectional ---


def test_r11_noop_without_file_locations(tmp_path):
    configure_disk(tmp_path)
    touch(tmp_path / "fixtures" / "data" / "111" / "stray.txt")
    corpus = corpus_of(
        structure("guildid", "urn:demo:type:guildid"),
        structure("api", "http://127.0.0.1:9420/api/feed"),
    )

    assert r11_fixture_tree_bidirectional(corpus) == []


def test_r11_clean_fixture_tree(tmp_path):
    configure_disk(tmp_path)
    touch(tmp_path / "fixtures" / "data" / "111" / "feeds.jsonl")
    touch(tmp_path / "fixtures" / "data" / "222" / "feeds.jsonl")
    corpus = corpus_of(structure("feed", FEED))

    assert r11_fixture_tree_bidirectional(corpus) == []


def test_r11_extra_actual_file_fails(tmp_path):
    configure_disk(tmp_path)
    matching = touch(tmp_path / "fixtures" / "data" / "111" / "feeds.jsonl")
    stray = touch(tmp_path / "fixtures" / "data" / "abc" / "feeds.jsonl")
    corpus = corpus_of(
        structure(
            "feed",
            FEED,
            Parameters={"guild": {"Type": "guildid", "Pattern": "[0-9]+"}},
        )
    )

    violations = r11_fixture_tree_bidirectional(corpus)

    assert len(violations) == 1
    assert violations[0].rule_id == "R11"
    assert violations[0].severity == "fail"
    assert violations[0].doc is None
    assert str(stray) in violations[0].message
    assert str(matching) not in violations[0].message


def test_r11_missing_expansion_fails(tmp_path):
    configure_disk(tmp_path)
    (tmp_path / "fixtures").mkdir()
    corpus = corpus_of(structure("feed", FEED))

    violations = r11_fixture_tree_bidirectional(corpus)

    assert len(violations) == 1
    assert violations[0].rule_id == "R11"
    assert violations[0].severity == "fail"
    assert violations[0].doc == "feed"
    assert FEED in violations[0].message


def test_r11_fixtures_absent_with_file_location(tmp_path):
    configure_disk(tmp_path)
    corpus = corpus_of(structure("feed", FEED))

    violations = r11_fixture_tree_bidirectional(corpus)

    assert [v.doc for v in violations] == ["feed"]
    assert all(v.severity == "fail" for v in violations)


def test_r11_unconfigured_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(zhizong.disk, "_contracts_root", None)
    corpus = corpus_of(structure("feed", FEED))

    with pytest.raises(RuntimeError, match="configure_disk"):
        r11_fixture_tree_bidirectional(corpus)


# --- R12: real data tree ---


def test_r12_noop_without_data_root(tmp_path):
    configure_disk(tmp_path)  # data_root deliberately None (0.1.0 deferral)
    corpus = corpus_of(structure("feed", FEED))

    assert r12_real_tree_matches(corpus) == []


def test_r12_noop_without_file_locations(tmp_path):
    configure_disk(tmp_path, data_root=tmp_path / "data")
    corpus = corpus_of(structure("guildid", "urn:demo:type:guildid"))

    assert r12_real_tree_matches(corpus) == []


def test_r12_unknown_actual_file_fails(tmp_path):
    configure_disk(tmp_path, data_root=tmp_path / "data")
    touch(tmp_path / "data" / "data" / "111" / "feeds.jsonl")
    stray = touch(tmp_path / "data" / "data" / "111" / "extra.txt")
    corpus = corpus_of(structure("feed", FEED))

    violations = r12_real_tree_matches(corpus)

    assert len(violations) == 1
    assert violations[0].rule_id == "R12"
    assert violations[0].severity == "fail"
    assert violations[0].doc is None
    assert str(stray) in violations[0].message


def test_r12_missing_expansion_non_generated_warns(tmp_path):
    configure_disk(tmp_path, data_root=tmp_path / "data")
    (tmp_path / "data").mkdir()
    corpus = corpus_of(structure("feed", FEED))

    violations = r12_real_tree_matches(corpus)

    assert len(violations) == 1
    assert violations[0].rule_id == "R12"
    assert violations[0].severity == "warn"
    assert violations[0].doc == "feed"


def test_r12_generated_lifecycle_exempt(tmp_path):
    configure_disk(tmp_path, data_root=tmp_path / "data")
    (tmp_path / "data").mkdir()
    corpus = corpus_of(structure("feed", FEED, Lifecycle="generated"))

    assert r12_real_tree_matches(corpus) == []


def test_r12_multisegment_expansion_with_pattern_filtering(tmp_path):
    configure_disk(tmp_path, data_root=tmp_path / "data")
    touch(tmp_path / "data" / "data" / "111" / "20260101" / "feeds.jsonl")
    touch(tmp_path / "data" / "data" / "222" / "snapshot" / "feeds.jsonl")
    stray = touch(tmp_path / "data" / "data" / "abc" / "20260101" / "feeds.jsonl")
    corpus = corpus_of(
        structure(
            "feed",
            "file:data/{guild}/{day}/feeds.jsonl",
            Parameters={
                "guild": {"Type": "guildid", "Pattern": "[0-9]+"},
                "day": {"Type": "dayid"},
            },
        )
    )

    violations = r12_real_tree_matches(corpus)

    assert len(violations) == 1
    assert violations[0].severity == "fail"
    assert violations[0].doc is None
    assert str(stray) in violations[0].message
