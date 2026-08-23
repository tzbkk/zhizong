"""Sample-pair rules R13/R14/R15 (grammar Invariants, all OnViolation: fail).

R13 — a structure whose Location scheme is ``file`` or ``http`` (urn-exempt)
      must carry BOTH ``<contracts_root>/samples/<Name>.valid.<ext>`` and
      ``.invalid.<ext>``. Extension derivation per
      Semantics.Samples.Extensions: http → ``json``; a file Location ending
      ``.jsonl`` → ``jsonl``; otherwise → ``txt``.
R14 — every valid-sample entry must pass the structure's checks.
R15 — every invalid-sample entry must be rejected; an entry that passes is
      the violation.

Entry semantics by extension and Form (minimal, no grammar engine):

- ``json``: the whole file is a single JSON entry (http payloads).
- ``jsonl``: every non-blank line is a JSON entry (blank lines skipped).
- ``txt`` + Form=grammar: LINE-LEVEL REGEX matching — every ``/.../`` regex
  literal extracted from the Productions string must ``re.search`` the line;
  literals that fail ``re.compile`` are skipped, and a Productions block
  with no extractable literal imposes no constraint. This is deliberately
  minimal: no productions parsing, token streams, or rule combinators.
- ``txt`` + Form=record: each line is parsed as JSON and schema-checked
  (completion choice: Extensions defines ``txt`` only for non-JSONL grammar
  text; JSON parsing keeps record semantics on record structures).
- ``txt`` + Form=scalar: each line is checked against Definition.Pattern
  (same line-regex stance as grammar).

Record entries are checked against the field-table-compiled JSON Schema via
an explicit ``jsonschema.Draft202012Validator``. A record structure whose
table fails to compile (unknown reference, cycle) yields one violation
carrying the compiler error instead of crashing the run.

The sample tree lives on disk, so the module keeps a module-level
``configure_samples(contracts_root)`` setter (mirroring the T5 pattern);
T7's CLI must call it before running rules. Running the rules without a
configured root raises ``RuntimeError``.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from zhizong.compile import compile_structure
from zhizong.loader import Corpus
from zhizong.registry import Violation, rule, severity_of

__all__ = [
    "configure_samples",
    "r13_sample_pairs_exist",
    "r14_valid_samples_pass",
    "r15_invalid_samples_rejected",
]

_contracts_root: Path | None = None


def configure_samples(contracts_root: Path | str) -> None:
    """Set the contracts root used to locate ``<root>/samples/``.

    T7's CLI must call this before running the sample rules.
    """

    global _contracts_root
    _contracts_root = Path(contracts_root)


def _require_root() -> Path:
    if _contracts_root is None:
        raise RuntimeError(
            "samples root not configured: call"
            " zhizong.samples.configure_samples(contracts_root) before"
            " running sample rules (the CLI must do this)"
        )
    return _contracts_root


@dataclass(frozen=True)
class _Entry:
    locator: str
    raw: str
    parsed: Any = None
    parse_error: str | None = None


@rule("R13")
def r13_sample_pairs_exist(corpus: Corpus) -> list[Violation]:
    """Location file/http structures must carry both sample files; urn-exempt."""

    root = _require_root()
    out: list[Violation] = []
    for name, doc in corpus.structures().items():
        if _location_scheme(doc) not in ("file", "http"):
            continue
        ext = _sample_ext(doc)
        for kind in ("valid", "invalid"):
            path = _sample_path(root, name, kind, ext)
            if not path.is_file():
                out.append(
                    Violation(
                        "R13",
                        name,
                        f"missing sample file: {path}",
                        severity_of("R13"),
                    )
                )
    return out


@rule("R14")
def r14_valid_samples_pass(corpus: Corpus) -> list[Violation]:
    """Every valid-sample entry must pass the structure's checks."""

    return _check_samples(corpus, "valid", "R14")


@rule("R15")
def r15_invalid_samples_rejected(corpus: Corpus) -> list[Violation]:
    """Every invalid-sample entry must be rejected; passing entries violate."""

    return _check_samples(corpus, "invalid", "R15")


def _check_samples(corpus: Corpus, kind: str, rule_id: str) -> list[Violation]:
    root = _require_root()
    out: list[Violation] = []
    for name, doc in corpus.structures().items():
        if _location_scheme(doc) not in ("file", "http"):
            continue
        ext = _sample_ext(doc)
        path = _sample_path(root, name, kind, ext)
        if not path.is_file():
            continue  # existence is R13's job
        form = _form(doc)
        compiled: dict | None = None
        if form == "record":
            try:
                compiled = compile_structure(doc, corpus)
            except ValueError as exc:
                out.append(
                    Violation(
                        rule_id,
                        name,
                        f"field table does not compile: {exc}",
                        severity_of(rule_id),
                    )
                )
                continue
        for entry in _iter_entries(path, ext, form):
            failure = _entry_failure(doc, entry, compiled)
            if kind == "valid" and failure is not None:
                out.append(
                    Violation(
                        rule_id,
                        name,
                        f"{entry.locator}: valid sample rejected: {failure}",
                        severity_of(rule_id),
                    )
                )
            elif kind == "invalid" and failure is None:
                out.append(
                    Violation(
                        rule_id,
                        name,
                        f"{entry.locator}: invalid sample accepted"
                        " (must be rejected by the structure's checks)",
                        severity_of(rule_id),
                    )
                )
    return out


def _location_scheme(doc: dict) -> str | None:
    location = doc.get("Location")
    if not isinstance(location, str) or ":" not in location:
        return None
    return location.split(":", 1)[0]


def _sample_ext(doc: dict) -> str:
    if _location_scheme(doc) == "http":
        return "json"
    location = doc.get("Location", "")
    return "jsonl" if location.endswith(".jsonl") else "txt"


def _sample_path(root: Path, name: str, kind: str, ext: str) -> Path:
    return root / "samples" / f"{name}.{kind}.{ext}"


def _form(doc: dict) -> Any:
    definition = doc.get("Definition")
    return definition.get("Form") if isinstance(definition, dict) else None


def _iter_entries(path: Path, ext: str, form: Any) -> Iterator[_Entry]:
    text = path.read_text(encoding="utf-8")
    if ext == "json":
        yield _parse_json_entry(path, text, None)
        return
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if ext == "jsonl" or (ext == "txt" and form == "record"):
            yield _parse_json_entry(path, line, lineno)
        else:
            yield _Entry(locator=f"{path}:{lineno}", raw=line)


def _parse_json_entry(path: Path, text: str, lineno: int | None) -> _Entry:
    locator = str(path) if lineno is None else f"{path}:{lineno}"
    try:
        return _Entry(locator=locator, raw=text, parsed=json.loads(text))
    except json.JSONDecodeError as exc:
        return _Entry(
            locator=locator, raw=text, parse_error=f"JSON parse error: {exc.msg}"
        )


def _entry_failure(doc: dict, entry: _Entry, compiled: dict | None) -> str | None:
    if entry.parse_error is not None:
        return entry.parse_error

    form = _form(doc)
    if form == "grammar":
        for regex in _productions_regexes(doc):
            if regex.search(entry.raw) is None:
                return (
                    f"line does not match production regex /{regex.pattern}/"
                )
        return None
    if form == "scalar":
        return _scalar_failure(doc, entry)

    validator = jsonschema.Draft202012Validator(compiled or {})
    error = next(validator.iter_errors(entry.parsed), None)
    if error is None:
        return None
    location = "/".join(str(part) for part in error.absolute_path)
    prefix = f"{location}: " if location else ""
    return f"{prefix}{error.message}"


def _scalar_failure(doc: dict, entry: _Entry) -> str | None:
    pattern = (doc.get("Definition") or {}).get("Pattern")
    if not isinstance(pattern, str) or not pattern:
        return None
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"scalar Pattern does not compile: {exc}"
    if regex.search(entry.raw) is None:
        return f"line does not match scalar pattern /{pattern}/"
    return None


def _productions_regexes(doc: dict) -> tuple[re.Pattern, ...]:
    productions = (doc.get("Definition") or {}).get("Productions") or ""
    return _compile_regexes(str(productions))


@functools.lru_cache(maxsize=None)
def _compile_regexes(productions: str) -> tuple[re.Pattern, ...]:
    out = []
    for body in re.findall(r"/([^/\n]+)/", productions):
        try:
            out.append(re.compile(body))
        except re.error:
            continue
    return tuple(out)
