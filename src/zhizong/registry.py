"""Rule registry: Violation reporting primitive and the R18 closure mechanism.

Import layering (cycle-free): loader and shapes import this module; this module
never imports sibling package modules at runtime — the grammar is read straight
from the package data files (``zhizong/versions/*.yaml``).
"""

from __future__ import annotations

import functools
import importlib.resources
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import yaml

if TYPE_CHECKING:
    from zhizong.loader import Corpus

__all__ = [
    "RegistryError",
    "Violation",
    "assert_closure",
    "document_ids",
    "implemented_ids",
    "invariant",
    "rule",
    "severity_of",
]


@dataclass(frozen=True)
class Violation:
    """A single validation finding — the reporting primitive (CLI is T7).

    rule_id: an Invariant id ("R16") for registry-managed rules, or the
        pseudo-id "Shapes.Document" for JSON-Schema shape-layer findings
        (including load-time rejects: unparseable or Name-less YAML files).
    doc: the offending document's Name as keyed in ``Corpus.documents``
        (int for version generations, str otherwise; None for corpus- or
        file-level findings that cannot be attributed to a document).
    message: human-readable description of the finding.
    severity: "fail" or "warn", wired from the rule's OnViolation field.
    """

    rule_id: str
    doc: object
    message: str
    severity: Literal["fail", "warn"]


class RegistryError(Exception):
    """Invalid rule registration: duplicate or grammar-unknown rule id."""


RuleFn = Callable[["Corpus"], list[Violation]]

_RULES: dict[str, RuleFn] = {}


def rule(rule_id: str) -> Callable[[RuleFn], RuleFn]:
    """Register a check function under an explicit grammar Invariant id.

    Rule function convention (T4-T7 build on this):
    ``fn(corpus: Corpus) -> list[Violation]`` — pure, no I/O.
    Duplicate ids and ids not declared by the grammar's Invariants are
    rejected at decoration time.
    """

    def register(fn: RuleFn) -> RuleFn:
        if rule_id in _RULES:
            raise RegistryError(f"duplicate rule registration: {rule_id}")
        if rule_id not in document_ids():
            raise RegistryError(
                f"unknown rule id: {rule_id} is not declared by the grammar's Invariants"
            )
        _RULES[rule_id] = fn
        return fn

    return register


def implemented_ids() -> set[str]:
    """Ids registered so far ({R16, R19} at task 3; grows through T4-T6)."""

    return set(_RULES)


@functools.lru_cache(maxsize=1)
def _latest_version_doc() -> dict | None:
    base = importlib.resources.files("zhizong") / "versions"
    docs = []
    for entry in sorted(base.iterdir(), key=lambda e: e.name):
        if entry.is_file() and entry.name.endswith(".yaml"):
            with entry.open("r", encoding="utf-8") as f:
                parsed = yaml.safe_load(f)
            if isinstance(parsed, dict) and parsed.get("Type") == "version":
                docs.append(parsed)
    return max(docs, key=lambda d: d.get("Name", 0)) if docs else None


def document_ids() -> set[str]:
    """Ids declared by the injected grammar's Invariants (latest generation)."""

    doc = _latest_version_doc()
    if doc is None:
        return set()
    return {inv["Id"] for inv in doc.get("Definition", {}).get("Invariants", [])}


def invariant(rule_id: str) -> dict:
    """The grammar's Invariant entry: {Id, OnViolation, Scope, Statement}."""

    doc = _latest_version_doc()
    if doc is None:
        raise RegistryError("no system version document available in package")
    for inv in doc.get("Definition", {}).get("Invariants", []):
        if inv["Id"] == rule_id:
            return inv
    raise RegistryError(f"unknown rule id: {rule_id}")


def severity_of(rule_id: str) -> Literal["fail", "warn"]:
    """Severity wired from the Invariant's OnViolation field (R17: fail)."""

    return invariant(rule_id)["OnViolation"]


def assert_closure() -> None:
    """R18: implemented rule ids must exactly equal the grammar's Invariant ids.

    Bidirectional: flags both unimplemented documented ids and undocumented
    implementations. Turns non-raising once T4-T7 register R01-R15, R17, R20
    (R18 itself must be registered by T7, e.g. as a rule whose body calls
    this function, for the equality to include it).
    """

    implemented = implemented_ids()
    documented = document_ids()
    if implemented != documented:
        raise AssertionError(
            "R18 closure violated:"
            f" unimplemented={sorted(documented - implemented)}"
            f" undocumented={sorted(implemented - documented)}"
        )
