"""Sample rules tests: R13 pair existence, R14 valid-pass, R15 invalid-rejected.

Includes the tolerance locks: unknown upstream fields in valid samples MUST
pass (R14) and invalid samples missing required fields MUST be rejected (R15).
"""

import json

import pytest

from zhizong import samples
from zhizong.loader import Corpus
from zhizong.samples import (
    configure_samples,
    r13_sample_pairs_exist,
    r14_valid_samples_pass,
    r15_invalid_samples_rejected,
)

LOG_PRODUCTIONS = (
    "entry ::= <ts> \" \" <level> \" \" <msg>\n"
    "ts    ::= /[0-9]{4}-[0-9]{2}-[0-9]{2}/\n"
    "level ::= /(DEBUG|INFO|WARN|ERROR)/\n"
    "msg   ::= /.+/"
)


def feed_record() -> dict:
    return {
        "SchemaVersion": 1,
        "Type": "structure",
        "Name": "FeedRecord",
        "Description": "feed entry",
        "Location": "file://data/feeds.jsonl",
        "Definition": {
            "Form": "record",
            "Table": [
                {
                    "Field": "id",
                    "Type": "string",
                    "Required": True,
                    "Description": "id",
                },
                {
                    "Field": "createTime",
                    "Type": "string",
                    "Required": True,
                    "Description": "ts",
                },
                {
                    "Field": "title",
                    "Type": "object",
                    "Description": "title block",
                    "Fields": [
                        {
                            "Field": "poster",
                            "Type": "string",
                            "Required": True,
                            "Description": "poster",
                        }
                    ],
                },
                {
                    "Field": "images",
                    "Type": "array<ImageRecord>",
                    "Description": "media",
                },
            ],
        },
    }


def image_record() -> dict:
    return {
        "SchemaVersion": 1,
        "Type": "structure",
        "Name": "ImageRecord",
        "Description": "image",
        "Location": "file://data/images.jsonl",
        "Definition": {
            "Form": "record",
            "Table": [
                {
                    "Field": "url",
                    "Type": "string",
                    "Required": True,
                    "Description": "url",
                }
            ],
        },
    }


def item_record() -> dict:
    """Exactly 3 declared fields — the tolerance-lock fixture."""
    return {
        "SchemaVersion": 1,
        "Type": "structure",
        "Name": "ItemRecord",
        "Description": "item",
        "Location": "file://data/items.jsonl",
        "Definition": {
            "Form": "record",
            "Table": [
                {
                    "Field": "id",
                    "Type": "string",
                    "Required": True,
                    "Description": "id",
                },
                {
                    "Field": "createTime",
                    "Type": "string",
                    "Required": True,
                    "Description": "ts",
                },
                {
                    "Field": "title",
                    "Type": "string",
                    "Description": "title",
                },
            ],
        },
    }


def grammar_log() -> dict:
    return {
        "SchemaVersion": 1,
        "Type": "structure",
        "Name": "AppLog",
        "Description": "log lines",
        "Location": "file://log/app.log",
        "Definition": {"Form": "grammar", "Productions": LOG_PRODUCTIONS},
    }


def http_record() -> dict:
    doc = {
        "SchemaVersion": 1,
        "Type": "structure",
        "Name": "ApiPayload",
        "Description": "http payload",
        "Location": "http://127.0.0.1:9420/api/feed",
        "Definition": {
            "Form": "record",
            "Table": [
                {
                    "Field": "code",
                    "Type": "integer",
                    "Required": True,
                    "Description": "code",
                }
            ],
        },
    }
    return doc


def record_txt_structure() -> dict:
    return {
        "SchemaVersion": 1,
        "Type": "structure",
        "Name": "LineItems",
        "Description": "one JSON record per text line",
        "Location": "file://data/items.txt",
        "Definition": {
            "Form": "record",
            "Table": [
                {
                    "Field": "id",
                    "Type": "string",
                    "Required": True,
                    "Description": "id",
                }
            ],
        },
    }


def scalar_structure() -> dict:
    return {
        "SchemaVersion": 1,
        "Type": "structure",
        "Name": "FeedId",
        "Description": "scalar id",
        "Location": "urn:demo:type:FeedId",
        "Definition": {"Form": "scalar", "Base": "string", "Pattern": "^feed-.+$"},
    }


def corpus_of(*docs: dict) -> Corpus:
    return Corpus(
        documents={d["Name"]: d for d in docs},
        externals={},
        violations=[],
        system_names=frozenset(),
    )


def write_sample(root, filename: str, text: str) -> None:
    sdir = root / "samples"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / filename).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- R13


def test_r13_all_pairs_present_passes(tmp_path):
    write_sample(tmp_path, "FeedRecord.valid.jsonl", '{"id": "1"}\n')
    write_sample(tmp_path, "FeedRecord.invalid.jsonl", "broken\n")
    write_sample(tmp_path, "ImageRecord.valid.jsonl", '{"url": "u"}\n')
    write_sample(tmp_path, "ImageRecord.invalid.jsonl", "broken\n")
    write_sample(tmp_path, "AppLog.valid.txt", "2026-01-01 INFO up\n")
    write_sample(tmp_path, "AppLog.invalid.txt", "bad line\n")
    write_sample(tmp_path, "ApiPayload.valid.json", '{"code": 0}')
    write_sample(tmp_path, "ApiPayload.invalid.json", "{}")
    configure_samples(tmp_path)

    corpus = corpus_of(feed_record(), image_record(), grammar_log(), http_record())

    assert r13_sample_pairs_exist(corpus) == []


def test_r13_flags_each_missing_sample_file_with_derived_ext(tmp_path):
    configure_samples(tmp_path)

    corpus = corpus_of(feed_record(), grammar_log(), http_record())
    violations = r13_sample_pairs_exist(corpus)

    assert [v.rule_id for v in violations] == ["R13"] * 6
    assert all(v.severity == "fail" for v in violations)
    docs = {v.doc for v in violations}
    assert docs == {"FeedRecord", "AppLog", "ApiPayload"}
    joined = "\n".join(v.message for v in violations)
    for filename in (
        "FeedRecord.valid.jsonl",
        "FeedRecord.invalid.jsonl",
        "AppLog.valid.txt",
        "AppLog.invalid.txt",
        "ApiPayload.valid.json",
        "ApiPayload.invalid.json",
    ):
        assert filename in joined


def test_r13_urn_structures_exempt_from_sample_requirement(tmp_path):
    configure_samples(tmp_path)

    assert r13_sample_pairs_exist(corpus_of(scalar_structure())) == []


# ---------------------------------------------------------------- R14


def test_tolerance_lock_valid_sample_with_unknown_field_passes_r14(tmp_path):
    entry = {
        "id": "feed-1",
        "createTime": "2026-01-01T00:00:00Z",
        "title": "hello",
        "unknownUpstreamField": {"deep": [1, 2]},
    }
    write_sample(
        tmp_path, "ItemRecord.valid.jsonl", json.dumps(entry) + "\n"
    )
    configure_samples(tmp_path)

    assert r14_valid_samples_pass(corpus_of(item_record())) == []


def test_r14_full_feed_fixture_with_nested_records_passes(tmp_path):
    valid = {
        "id": "feed-1",
        "createTime": "2026-01-01T00:00:00Z",
        "title": {"poster": "alice", "extraTitleField": 1},
        "images": [{"url": "http://x/1.png"}, {"url": "http://x/2.png", "w": 2}],
        "unknownTop": None,
    }
    write_sample(tmp_path, "FeedRecord.valid.jsonl", json.dumps(valid) + "\n")
    write_sample(
        tmp_path,
        "FeedRecord.invalid.jsonl",
        json.dumps({"id": "feed-2"}) + "\n"
        + json.dumps({"id": "f", "createTime": "t", "title": {}}) + "\n"
        + json.dumps(
            {
                "id": "f",
                "createTime": "t",
                "title": {"poster": "p"},
                "images": [{"no_url": 1}],
            }
        )
        + "\n",
    )
    configure_samples(tmp_path)

    corpus = corpus_of(feed_record(), image_record())

    assert r14_valid_samples_pass(corpus) == []
    assert r15_invalid_samples_rejected(corpus) == []


def test_r14_flags_valid_entry_missing_required_field(tmp_path):
    write_sample(
        tmp_path,
        "ItemRecord.valid.jsonl",
        '{"id": "ok", "createTime": "t", "title": "a"}\n'
        '{"createTime": "t", "title": "b"}\n',
    )
    configure_samples(tmp_path)

    violations = r14_valid_samples_pass(corpus_of(item_record()))

    assert len(violations) == 1
    v = violations[0]
    assert v.rule_id == "R14"
    assert v.doc == "ItemRecord"
    assert v.severity == "fail"
    assert "ItemRecord.valid.jsonl:2" in v.message
    assert "id" in v.message


def test_r14_flags_unparseable_jsonl_line(tmp_path):
    write_sample(tmp_path, "ItemRecord.valid.jsonl", "not json at all\n")
    configure_samples(tmp_path)

    violations = r14_valid_samples_pass(corpus_of(item_record()))

    assert len(violations) == 1
    assert violations[0].rule_id == "R14"
    assert "ItemRecord.valid.jsonl:1" in violations[0].message


def test_r14_grammar_txt_lines_checked_by_line_regex(tmp_path):
    write_sample(
        tmp_path,
        "AppLog.valid.txt",
        "2026-01-01 INFO started\n\n2026-01-02 ERROR boom\n",
    )
    write_sample(tmp_path, "AppLog.invalid.txt", "no timestamp DEBUG here\n")
    configure_samples(tmp_path)

    corpus = corpus_of(grammar_log())

    assert r14_valid_samples_pass(corpus) == []
    assert r15_invalid_samples_rejected(corpus) == []


def test_r14_grammar_regex_violation_reported_per_line(tmp_path):
    write_sample(tmp_path, "AppLog.valid.txt", "2026-01-01 INFO ok\nbad line\n")
    configure_samples(tmp_path)

    violations = r14_valid_samples_pass(corpus_of(grammar_log()))

    assert len(violations) == 1
    assert violations[0].doc == "AppLog"
    assert "AppLog.valid.txt:2" in violations[0].message


def test_r14_record_txt_lines_parsed_as_json(tmp_path):
    write_sample(
        tmp_path,
        "LineItems.valid.txt",
        '{"id": "a"}\n{"id": "b", "extra": 1}\n',
    )
    configure_samples(tmp_path)

    assert r14_valid_samples_pass(corpus_of(record_txt_structure())) == []


def test_r14_record_txt_unparseable_line_flagged(tmp_path):
    write_sample(tmp_path, "LineItems.valid.txt", '{"id": "a"}\nplain text\n')
    configure_samples(tmp_path)

    violations = r14_valid_samples_pass(corpus_of(record_txt_structure()))

    assert len(violations) == 1
    assert "LineItems.valid.txt:2" in violations[0].message


def test_r14_http_json_single_object(tmp_path):
    write_sample(tmp_path, "ApiPayload.valid.json", '{"code": 0, "extra": 9}')
    configure_samples(tmp_path)

    assert r14_valid_samples_pass(corpus_of(http_record())) == []


def test_r14_skips_structures_without_sample_files(tmp_path):
    configure_samples(tmp_path)

    assert r14_valid_samples_pass(corpus_of(feed_record(), image_record())) == []


# ---------------------------------------------------------------- R15


def test_tolerance_lock_invalid_sample_missing_required_field_rejected_r15(
    tmp_path,
):
    write_sample(
        tmp_path,
        "ItemRecord.invalid.jsonl",
        '{"createTime": "t", "title": "b"}\n{"title": "no id"}\n',
    )
    configure_samples(tmp_path)

    assert r15_invalid_samples_rejected(corpus_of(item_record())) == []


def test_r15_flags_invalid_entry_that_passes(tmp_path):
    passing = {
        "id": "feed-9",
        "createTime": "2026-01-01T00:00:00Z",
        "title": "fine",
        "unknown": 1,
    }
    write_sample(
        tmp_path, "ItemRecord.invalid.jsonl", json.dumps(passing) + "\n"
    )
    configure_samples(tmp_path)

    violations = r15_invalid_samples_rejected(corpus_of(item_record()))

    assert len(violations) == 1
    v = violations[0]
    assert v.rule_id == "R15"
    assert v.doc == "ItemRecord"
    assert v.severity == "fail"
    assert "ItemRecord.invalid.jsonl:1" in v.message


def test_r15_flags_grammar_line_that_matches_productions(tmp_path):
    write_sample(tmp_path, "AppLog.invalid.txt", "2026-01-01 INFO looks fine\n")
    configure_samples(tmp_path)

    violations = r15_invalid_samples_rejected(corpus_of(grammar_log()))

    assert len(violations) == 1
    assert violations[0].rule_id == "R15"
    assert "AppLog.invalid.txt:1" in violations[0].message


def test_r15_http_json_object_passing_schema_is_flagged(tmp_path):
    write_sample(tmp_path, "ApiPayload.invalid.json", '{"code": 1}')
    configure_samples(tmp_path)

    violations = r15_invalid_samples_rejected(corpus_of(http_record()))

    assert len(violations) == 1
    assert violations[0].doc == "ApiPayload"


def test_r15_unparseable_invalid_line_counts_as_rejected(tmp_path):
    write_sample(tmp_path, "ItemRecord.invalid.jsonl", "definitely not json\n")
    configure_samples(tmp_path)

    assert r15_invalid_samples_rejected(corpus_of(item_record())) == []


def test_rules_require_configured_root():
    samples._contracts_root = None

    with pytest.raises(RuntimeError, match="configure_samples"):
        r13_sample_pairs_exist(corpus_of(feed_record()))
