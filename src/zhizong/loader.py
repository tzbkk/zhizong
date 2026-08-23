"""Corpus loader: consumer contract documents plus the injected system grammar.

``load_corpus`` is pure with respect to the filesystem contract: it takes a
Path, scans ``<contracts_root>/**/*.yaml`` and returns a :class:`Corpus`. The
system grammar shipped inside the package (``zhizong/versions/*.yaml``) is
always injected as documents; a consumer document colliding with a system
document Name yields an R17 violation and the system document stays
authoritative. Load-time rejects (unparseable or Name-less YAML) are recorded
as violations, never raised.
"""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from zhizong.registry import Violation, severity_of

SHAPE_RULE_ID = "Shapes.Document"

_PARSE_FAILED = object()


@dataclass
class Corpus:
    """The validation unit handed to every rule function.

    documents: Name -> parsed document (consumer docs + injected system
        version docs; version generations key by int Name, e.g. ``1``).
    externals: parsed ``<contracts_root>/externals.yaml`` ({} when absent).
    violations: load-time findings (bad YAML, Name-less files, injection
        collisions); rule outputs are produced separately by the checks.
    system_names: Names of the injected system documents.
    """

    documents: dict[Any, dict] = field(default_factory=dict)
    externals: dict = field(default_factory=dict)
    violations: list[Violation] = field(default_factory=list)
    system_names: frozenset = frozenset()

    def versions(self) -> dict[Any, dict]:
        return {
            name: doc
            for name, doc in self.documents.items()
            if isinstance(doc, dict) and doc.get("Type") == "version"
        }

    def components(self) -> dict[Any, dict]:
        return {
            name: doc
            for name, doc in self.documents.items()
            if isinstance(doc, dict) and doc.get("Type") == "component"
        }

    def structures(self) -> dict[Any, dict]:
        return {
            name: doc
            for name, doc in self.documents.items()
            if isinstance(doc, dict) and doc.get("Type") == "structure"
        }

    def latest_system_version(self) -> dict | None:
        candidates = [
            self.documents[name]
            for name in self.system_names
            if name in self.documents
        ]
        return max(candidates, key=lambda d: d.get("Name", 0)) if candidates else None


def load_corpus(contracts_root: Path | str) -> Corpus:
    """Load every ``<root>/**/*.yaml`` document plus the injected system grammar.

    A missing ``contracts_root`` is legal: the corpus then carries only the
    injected system documents. ``externals.yaml`` at the root is loaded into
    ``Corpus.externals`` and never into ``documents``. Within-consumer
    duplicate Names keep the first occurrence and emit nothing — flagging
    them is R17's job (T4-T6).
    """

    root = Path(contracts_root)
    documents: dict[Any, dict] = {}
    violations: list[Violation] = []
    externals: dict = {}

    externals_path = root / "externals.yaml"
    if externals_path.is_file():
        parsed = _parse_yaml(externals_path, violations)
        if isinstance(parsed, dict):
            externals = parsed
        elif parsed is not _PARSE_FAILED and parsed is not None:
            violations.append(
                Violation(
                    SHAPE_RULE_ID,
                    None,
                    f"{externals_path}: externals must be a mapping,"
                    f" got {type(parsed).__name__}",
                    "fail",
                )
            )

    if root.is_dir():
        for path in sorted(root.rglob("*.yaml")):
            if path == externals_path:
                continue
            parsed = _parse_yaml(path, violations)
            if parsed is _PARSE_FAILED:
                continue
            if not isinstance(parsed, dict) or "Name" not in parsed:
                violations.append(
                    Violation(
                        SHAPE_RULE_ID,
                        None,
                        f"{path}: not a contract document (no top-level Name); skipped",
                        "fail",
                    )
                )
                continue
            name = parsed["Name"]
            try:
                hash(name)
            except TypeError:
                violations.append(
                    Violation(
                        SHAPE_RULE_ID,
                        None,
                        f"{path}: Name is unhashable"
                        f" ({type(name).__name__}); skipped",
                        "fail",
                    )
                )
                continue
            if name in documents:
                continue
            documents[name] = parsed

    system_names: set = set()
    for name, doc in _load_system_documents():
        if name in documents:
            violations.append(
                Violation(
                    "R17",
                    name,
                    f"consumer document {name!r} collides with the injected"
                    " system version document; system grammar remains authoritative",
                    severity_of("R17"),
                )
            )
        documents[name] = doc
        system_names.add(name)

    return Corpus(
        documents=documents,
        externals=externals,
        violations=violations,
        system_names=frozenset(system_names),
    )


def _parse_yaml(path: Path, violations: list[Violation]) -> object:
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as exc:
        violations.append(
            Violation(
                SHAPE_RULE_ID, None, f"{path}: YAML parse error: {exc}", "fail"
            )
        )
        return _PARSE_FAILED


def _load_system_documents() -> list[tuple[Any, dict]]:
    base = importlib.resources.files("zhizong") / "versions"
    out = []
    for entry in sorted(base.iterdir(), key=lambda e: e.name):
        if not (entry.is_file() and entry.name.endswith(".yaml")):
            continue
        with entry.open("r", encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        if isinstance(doc, dict) and "Name" in doc:
            out.append((doc["Name"], doc))
    return out
