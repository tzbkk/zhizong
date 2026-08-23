"""Registry tests: closure (R18), registration discipline, Violation primitive."""

import pytest

import zhizong.shapes  # noqa: F401 -- importing registers R16/R19
from zhizong.registry import (
    RegistryError,
    Violation,
    assert_closure,
    document_ids,
    implemented_ids,
    rule,
    severity_of,
)


def test_document_ids_come_from_grammar_invariants():
    assert document_ids() == {f"R{i:02d}" for i in range(1, 21)}


def test_severity_wired_from_on_violation():
    assert all(severity_of(rid) == "fail" for rid in document_ids())


def test_implemented_baseline_has_r16_r19_and_stays_within_document():
    assert {"R16", "R19"} <= implemented_ids()
    assert implemented_ids() <= document_ids()


def test_unknown_id_rejected():
    with pytest.raises(RegistryError):

        @rule("R99")
        def bogus(corpus):
            return []


def test_duplicate_id_rejected():
    with pytest.raises(RegistryError):

        @rule("R16")
        def duplicate(corpus):
            return []


@pytest.mark.xfail(reason="closure completes at T7 (R01-R15, R17, R20 pending)", strict=True)
def test_r18_closure_bidirectional():
    # Staged assertion (task 3): implemented == {R16, R19} today, so this test
    # genuinely fails and the strict xfail absorbs it. It turns green at T7
    # when all of R01-R20 are registered; strict=True then reports XPASS as an
    # error, forcing T7 to remove this marker.
    assert implemented_ids() == document_ids()
    assert_closure()


def test_violation_is_pure_data():
    v = Violation(rule_id="R16", doc="feeds", message="mismatch", severity="fail")

    assert v.rule_id == "R16"
    assert v.doc == "feeds"
    assert v.message == "mismatch"
    assert v.severity == "fail"
