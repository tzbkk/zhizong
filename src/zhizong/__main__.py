"""zhizong CLI: ``validate`` subcommand and ``--version``.

Exit-code contract (CI gate semantics):

* 0 — no fail-severity violations (warn-only also exits 0);
* 1 — at least one fail-severity violation;
* 2 — usage or configuration error (bad arguments, missing/invalid config).

Pipeline: load config → configure rule modules (location, samples, disk) →
load corpus → shape validation → every registered rule in sorted-id order →
report to stdout, one line per violation (``[R01] <doc> — <message>``)
followed by a summary line ``<N> document(s), <M> violation(s) (<F> fail,
<W> warn)`` where N counts consumer documents (the injected system grammar
is not part of the corpus under validation).

Importing this module imports every rule module so the registry is fully
populated before dispatch; the rule functions themselves are read from the
registry's internal table, which only this orchestrator consumes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import zhizong
from zhizong import disk, graph, location, samples, shapes  # noqa: F401
from zhizong.config import ConfigError, load_config
from zhizong.loader import Corpus, load_corpus
from zhizong.registry import Violation, _RULES

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_USAGE = 2


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"zhizong: {exc}", file=sys.stderr)
        return EXIT_USAGE

    contracts_root = Path(config["contracts_root"])
    location.configure_location(contracts_root, config["namespace"])
    samples.configure_samples(contracts_root)
    disk.configure_disk(contracts_root)

    corpus = load_corpus(contracts_root)
    violations = list(corpus.violations)
    violations.extend(shapes.validate_shapes(corpus))
    for rule_id in sorted(_RULES):
        violations.extend(_RULES[rule_id](corpus))

    _report(corpus, violations)
    if any(v.severity == "fail" for v in violations):
        return EXIT_VIOLATIONS
    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zhizong",
        description="Validate a corpus of contract documents against the"
        " grammar shipped inside the package.",
        epilog="Exit codes: 0 = no fail violations (warn-only is 0),"
        " 1 = at least one fail violation, 2 = usage or config error.",
    )
    parser.add_argument(
        "--version", action="version", version=zhizong.__version__
    )
    subparsers = parser.add_subparsers(
        dest="command", required=True, metavar="COMMAND"
    )
    validate = subparsers.add_parser(
        "validate", help="validate the contract corpus under contracts_root"
    )
    validate.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="config file path (default: .zhizong.yaml in the working"
        " directory)",
    )
    return parser


def _report(corpus: Corpus, violations: list[Violation]) -> None:
    consumer_documents = sum(
        1 for name in corpus.documents if name not in corpus.system_names
    )
    fail_count = sum(1 for v in violations if v.severity == "fail")
    warn_count = len(violations) - fail_count
    for violation in violations:
        doc_part = f"{violation.doc} — " if violation.doc is not None else ""
        print(f"[{violation.rule_id}] {doc_part}{violation.message}")
    print(
        f"{consumer_documents} document(s), {len(violations)} violation(s)"
        f" ({fail_count} fail, {warn_count} warn)"
    )


if __name__ == "__main__":
    raise SystemExit(main())
