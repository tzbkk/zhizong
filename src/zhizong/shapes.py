"""Shapes layer: JSON Schema document validation plus the R16/R19 rules.

validate_shapes checks every corpus document against the latest injected
system generation's ``Definition.Shapes.Document`` using an explicit
jsonschema.Draft202012Validator (bare ``jsonschema.validate`` is forbidden).
R16 and R19 are registered as the first two registry rules.
"""

from __future__ import annotations

import jsonschema

from zhizong.loader import SHAPE_RULE_ID, Corpus
from zhizong.registry import Violation, rule, severity_of


@rule("R16")
def r16_schema_version_matches_version_doc(corpus: Corpus) -> list[Violation]:
    """Every document's SchemaVersion must Name-match some version document.

    A missing SchemaVersion is left to the shape layer (Shapes.Document marks
    it required); R16 fires only on present values with no matching
    generation Name.
    """

    version_names = set(corpus.versions())
    out = []
    for name, doc in corpus.documents.items():
        if not isinstance(doc, dict):
            continue
        schema_version = doc.get("SchemaVersion")
        if schema_version is None:
            continue
        if schema_version not in version_names:
            out.append(
                Violation(
                    "R16",
                    name,
                    f"SchemaVersion {schema_version!r} matches no version document Name",
                    severity_of("R16"),
                )
            )
    return out


@rule("R19")
def r19_version_docs_self_validate(corpus: Corpus) -> list[Violation]:
    """Each version document must pass its own Definition.Shapes.Document."""

    out = []
    for name, doc in corpus.versions().items():
        definition = doc.get("Definition")
        schema = (
            definition.get("Shapes", {}).get("Document")
            if isinstance(definition, dict)
            else None
        )
        if schema is None:
            out.append(
                Violation(
                    "R19",
                    name,
                    "version document declares no Definition.Shapes.Document"
                    " to validate against",
                    severity_of("R19"),
                )
            )
            continue
        validator = jsonschema.Draft202012Validator(schema)
        for error in validator.iter_errors(doc):
            out.append(
                Violation(
                    "R19", name, _format_error(error), severity_of("R19")
                )
            )
    return out


def validate_shapes(corpus: Corpus) -> list[Violation]:
    """Validate every document against the latest system Shapes.Document."""

    latest = corpus.latest_system_version()
    if latest is None:
        raise RuntimeError(
            "corpus carries no injected system version document;"
            " cannot resolve Shapes.Document"
        )
    schema = latest.get("Definition", {}).get("Shapes", {}).get("Document")
    validator = jsonschema.Draft202012Validator(schema)
    out = []
    for name, doc in corpus.documents.items():
        for error in validator.iter_errors(doc):
            out.append(
                Violation(SHAPE_RULE_ID, name, _format_error(error), "fail")
            )
    return out


def _format_error(error: jsonschema.ValidationError) -> str:
    location = "/".join(str(part) for part in error.absolute_path)
    prefix = f"{location}: " if location else ""
    return f"{prefix}{error.message}"
