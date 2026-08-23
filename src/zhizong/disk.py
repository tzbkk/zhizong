"""Disk-tree invariants R11 (fixture tree) and R12 (real data tree), plus the
R18 rule-set closure check.

Grammar statements (``zhizong/versions/1.yaml``, Definition.Invariants):

* R11 (system): fixture 数据树上,实际文件必须命中某 file Location 展开,
  且每个 file Location 展开必须存在对应文件。
* R12 (system): 真实数据树上,实际文件必须命中某 file Location 展开;
  声明 Location 缺失且 Lifecycle 非 generated 时告警。
* R18 (meta): 校验器实现的规则 ID 集合必须与本 Invariants 的 ID 集合
  严格相等。

Tree expansion (shared by both rules): a ``file:`` Location's path (the part
after ``file:``, e.g. ``data/{guild}/feeds.jsonl``) is walked segment by
segment against a tree root. A literal segment must exist on disk (a branch
that dies contributes nothing). A segment containing ``{var}`` enumerates the
child DIRECTORIES of the current directory; when the segment holds exactly
one variable and that variable's ``Parameters[var].Pattern`` is a compilable
regex, a child name survives only on ``re.fullmatch`` (missing Pattern → any
child matches). Variables in separate segments expand over all combinations
naturally through the walk. The expansion of a Location is the set of FILES
reachable this way; an empty set means the walk died (or ended on
directories).

R11 walks ``<contracts_root>/fixtures/``:

* direction (a) — every actual file under the root must be a member of some
  Location's expansion (violation doc=None: no structure owns the file);
* direction (b) — every file Location's expansion must contain at least one
  existing file (violation doc=structure Name).

R12 walks ``data_root`` with the same logic:

* an actual file matching no expansion is a fail (doc=None);
* a file Location whose expansion is empty is a WARNING when the structure's
  ``Lifecycle`` is not ``generated`` (tool products: 磁盘缺失不告警).
  Severity note: the grammar's OnViolation field for R12 reads ``fail`` and
  ``severity_of("R12")`` drives the fail case, while the warn case follows
  the Invariant Statement's 告警 semantics (Semantics.Lifecycle) — a
  deliberate per-case split, see issues.md.

No-op gates: both rules return [] when the corpus has no file-scheme
Location structures; R12 additionally returns [] when ``data_root`` is None
— the ``data_root`` config key is deliberately deferred by design (no
consumer yet), so the CLI never configures it and R12 stays dormant. R11
raises RuntimeError only when file Locations exist and the module was never
configured.

Configuration follows the T5/T6 pattern: the CLI must call
:func:`configure_disk` once before dispatching rules.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from zhizong.registry import (
    Violation,
    document_ids,
    implemented_ids,
    rule,
    severity_of,
)

if TYPE_CHECKING:
    from zhizong.loader import Corpus

__all__ = [
    "configure_disk",
    "r11_fixture_tree_bidirectional",
    "r12_real_tree_matches",
    "r18_rule_set_closure",
]

_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

FIXTURES_DIRNAME = "fixtures"

_contracts_root: Path | None = None
_data_root: Path | None = None


def configure_disk(
    contracts_root: Path | str, data_root: Path | str | None = None
) -> None:
    """Set the tree roots consumed by R11 (``<root>/fixtures/``) and R12.

    data_root: real-data tree root; None (the default) keeps R12 dormant —
        the data_root config key is deferred by design.
    """

    global _contracts_root, _data_root
    _contracts_root = Path(contracts_root)
    _data_root = Path(data_root) if data_root is not None else None


def _file_location_structures(
    corpus: Corpus,
) -> list[tuple[Any, dict, str]]:
    out = []
    for name, doc in sorted(corpus.structures().items(), key=lambda i: repr(i[0])):
        location = doc.get("Location") if isinstance(doc, dict) else None
        if isinstance(location, str) and location.startswith("file:"):
            out.append((name, doc, location))
    return out


def _patterns(doc: dict) -> dict[str, str]:
    """var -> compilable Pattern from ``Parameters[var].Pattern``."""

    params = doc.get("Parameters")
    out: dict[str, str] = {}
    if not isinstance(params, dict):
        return out
    for var, spec in params.items():
        if not isinstance(spec, dict):
            continue
        pattern = spec.get("Pattern")
        if isinstance(pattern, str):
            try:
                re.compile(pattern)
            except re.error:
                continue
            out[var] = pattern
    return out


def _expand(root: Path, location: str, patterns: dict[str, str]) -> set[Path]:
    """Concrete files reachable by walking the Location's path segments."""

    segments = [s for s in location[len("file:") :].split("/") if s]
    candidates = {root}
    for segment in segments:
        variables = _VAR_RE.findall(segment)
        advanced = set()
        for current in candidates:
            if not variables:
                candidate = current / segment
                if candidate.exists():
                    advanced.add(candidate)
            elif current.is_dir():
                for child in current.iterdir():
                    if not child.is_dir():
                        continue
                    if len(variables) == 1:
                        pattern = patterns.get(variables[0])
                        if (
                            pattern is not None
                            and re.fullmatch(pattern, child.name) is None
                        ):
                            continue
                    advanced.add(child)
        candidates = advanced
        if not candidates:
            break
    return {c for c in candidates if c.is_file()}


def _actual_files(root: Path) -> set[Path]:
    if not root.is_dir():
        return set()
    return {p for p in root.rglob("*") if p.is_file()}


@rule("R11")
def r11_fixture_tree_bidirectional(corpus: Corpus) -> list[Violation]:
    """Fixture tree under ``<contracts_root>/fixtures/`` must equal the union
    of file-Location expansions in both directions."""

    structures = _file_location_structures(corpus)
    if not structures:
        return []
    if _contracts_root is None:
        raise RuntimeError(
            "configure_disk() must be called before R11 can walk the"
            " fixture tree"
        )
    root = _contracts_root / FIXTURES_DIRNAME
    severity = severity_of("R11")

    out: list[Violation] = []
    union: set[Path] = set()
    for name, doc, location in structures:
        expanded = _expand(root, location, _patterns(doc))
        union |= expanded
        if not expanded:
            out.append(
                Violation(
                    "R11",
                    name,
                    f"Location {location!r} expands to no existing file"
                    f" under {root}",
                    severity,
                )
            )
    for path in sorted(
        (p for p in _actual_files(root) if p not in union), key=str
    ):
        out.append(
            Violation(
                "R11",
                None,
                f"fixture file {path} matches no file Location expansion"
                f" (root {root})",
                severity,
            )
        )
    return out


@rule("R12")
def r12_real_tree_matches(corpus: Corpus) -> list[Violation]:
    """Real data tree under ``data_root``: unknown files fail; declared but
    missing non-generated Locations warn."""

    structures = _file_location_structures(corpus)
    if not structures or _data_root is None:
        return []
    root = _data_root
    fail_severity = severity_of("R12")

    out: list[Violation] = []
    union: set[Path] = set()
    for name, doc, location in structures:
        expanded = _expand(root, location, _patterns(doc))
        union |= expanded
        if expanded:
            continue
        lifecycle = doc.get("Lifecycle")
        if lifecycle == "generated":
            continue
        out.append(
            Violation(
                "R12",
                name,
                f"Location {location!r} expands to no existing file under"
                f" {root} and Lifecycle is {lifecycle!r}, not 'generated'",
                "warn",
            )
        )
    for path in sorted(
        (p for p in _actual_files(root) if p not in union), key=str
    ):
        out.append(
            Violation(
                "R12",
                None,
                f"data file {path} matches no file Location expansion"
                f" (root {root})",
                fail_severity,
            )
        )
    return out


@rule("R18")
def r18_rule_set_closure(corpus: Corpus) -> list[Violation]:
    """Implemented rule ids must exactly equal the grammar's Invariant ids."""

    implemented = implemented_ids()
    documented = document_ids()
    if implemented == documented:
        return []
    parts = []
    missing = sorted(documented - implemented)
    extra = sorted(implemented - documented)
    if missing:
        parts.append("unimplemented documented ids: " + ", ".join(missing))
    if extra:
        parts.append("undocumented implemented ids: " + ", ".join(extra))
    return [
        Violation(
            "R18",
            None,
            "rule set closure broken; " + "; ".join(parts),
            severity_of("R18"),
        )
    ]
