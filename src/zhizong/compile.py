"""Field-table → JSON Schema (draft 2020-12) compiler.

Implements the normative mapping of ``Semantics.FieldTableCompilation``
(grammar shipped in ``zhizong/versions/1.yaml``):

1. base types map directly: string/integer/number/boolean
2. ``object`` WITH ``Fields`` → ``{type: object, properties: nested,
   additionalProperties: true}``
3. ``additionalProperties`` is ALWAYS ``true`` — never ``false``: the contract
   declares only consumed fields, unknown upstream fields are legal
4. ``object`` WITHOUT ``Fields`` → opaque ``{type: object}``
5. ``array<T>`` → ``{type: array, items: compile(T)}`` (nestable)
6. ``Required: true`` fields enter ``required``; an absent ``Required`` (or
   ``false``) means optional
7. a scalar-structure-name reference → the referenced structure's
   ``{type: Base, pattern: Pattern}``
8. a record-structure-name reference → the referenced record's compiled
   product is injected into the root schema's ``$defs`` and the field
   compiles to ``{"$ref": "#/$defs/<recordName>"}``; nested record references
   compile recursively in dependency order, and reference cycles fail
   loudly with ``ValueError``

Output conventions (deterministic, side-effect-free):
- the root schema and every ``$defs`` record product carry ``type``,
  ``properties``, ``required`` (possibly empty) and ``additionalProperties:
  true``; the root additionally carries ``$defs``
- inline nested objects (rule 2) omit ``required`` when no child is
  required, matching the normative rule shape
"""

from __future__ import annotations

import re

from zhizong.loader import Corpus

__all__ = ["compile_structure"]

_BASE_TYPES = ("string", "integer", "number", "boolean")
_ARRAY_RE = re.compile(r"^array<(.+)>$")


def compile_structure(structure_doc: dict, corpus: Corpus) -> dict:
    """Compile a Form=record structure's Definition.Table into a JSON Schema."""

    name = structure_doc.get("Name") if isinstance(structure_doc, dict) else None
    definition = structure_doc.get("Definition") if isinstance(structure_doc, dict) else None
    if not isinstance(definition, dict) or definition.get("Form") != "record":
        raise ValueError(
            f"structure {name!r}: only Form=record field tables compile"
            " to JSON Schema"
        )
    table = definition.get("Table")
    if not isinstance(table, list) or not table:
        raise ValueError(
            f"structure {name!r}: Form=record requires a non-empty Definition.Table"
        )

    defs: dict[str, dict] = {}
    stack: list[str] = []
    if name is not None:
        stack.append(name)
    properties, required = _compile_table(table, corpus, defs, stack)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": True,
        "$defs": defs,
    }


def _compile_table(
    table: list, corpus: Corpus, defs: dict[str, dict], stack: list[str]
) -> tuple[dict[str, dict], list[str]]:
    properties: dict[str, dict] = {}
    required: list[str] = []
    for entry in table:
        if not isinstance(entry, dict) or "Field" not in entry or "Type" not in entry:
            raise ValueError(f"malformed field-table item: {entry!r}")
        field = entry["Field"]
        properties[field] = _compile_type(entry["Type"], entry, corpus, defs, stack)
        if entry.get("Required") is True:
            required.append(field)
    return properties, required


def _compile_type(
    type_expr: str, entry: dict, corpus: Corpus, defs: dict[str, dict], stack: list[str]
) -> dict:
    array = _ARRAY_RE.match(type_expr)
    if array:
        inner = _compile_type(array.group(1).strip(), entry, corpus, defs, stack)
        return {"type": "array", "items": inner}
    if type_expr in _BASE_TYPES:
        return {"type": type_expr}
    if type_expr == "object":
        return _compile_inline_object(entry, corpus, defs, stack)
    return _compile_reference(type_expr, corpus, defs, stack)


def _compile_inline_object(
    entry: dict, corpus: Corpus, defs: dict[str, dict], stack: list[str]
) -> dict:
    fields = entry.get("Fields")
    if not isinstance(fields, list) or not fields:
        return {"type": "object"}
    properties, required = _compile_table(fields, corpus, defs, stack)
    nested: dict = {
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
    }
    if required:
        nested["required"] = required
    return nested


def _compile_reference(
    name: str, corpus: Corpus, defs: dict[str, dict], stack: list[str]
) -> dict:
    if name in stack:
        chain = " -> ".join([*stack[stack.index(name):], name])
        raise ValueError(f"record reference cycle in field table: {chain}")

    target = corpus.structures().get(name)
    if target is None:
        raise ValueError(
            f"field-table type {name!r} references a structure"
            " not present in the corpus"
        )

    definition = target.get("Definition") or {}
    form = definition.get("Form")
    if form == "scalar":
        base = definition.get("Base")
        pattern = definition.get("Pattern")
        if base not in _BASE_TYPES or not isinstance(pattern, str) or not pattern:
            raise ValueError(
                f"scalar structure {name!r} must declare a valid Base and"
                f" Pattern (got Base={base!r}, Pattern={pattern!r})"
            )
        return {"type": base, "pattern": pattern}

    if form == "record":
        if name not in defs:
            defs[name] = _compile_record_product(name, definition, corpus, defs, stack)
        return {"$ref": f"#/$defs/{name}"}

    raise ValueError(
        f"field-table type {name!r} references a structure of Form {form!r};"
        " only scalar and record references are compilable"
    )


def _compile_record_product(
    name: str,
    definition: dict,
    corpus: Corpus,
    defs: dict[str, dict],
    stack: list[str],
) -> dict:
    table = definition.get("Table")
    if not isinstance(table, list) or not table:
        raise ValueError(
            f"structure {name!r}: Form=record requires a non-empty"
            " Definition.Table"
        )
    stack.append(name)
    try:
        properties, required = _compile_table(table, corpus, defs, stack)
    finally:
        stack.pop()
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": True,
    }
