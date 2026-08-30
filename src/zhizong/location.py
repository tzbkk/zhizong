"""Location invariants R06-R10: template uniqueness, directive wiring,
parameter closure, scalar parameter targets, and urn addressing.

Grammar statements (``zhizong/versions/1.yaml``, Definition.Invariants):

* R06 (structure × structure): Location 模板展开后全局唯一。
* R07 (component × structure): http 接线由指令边承载——path 变量闭包、
  动词方向纪律、声明唯一性(见 :func:`http_directive_wiring`)。
* R08 (structure): Location 中每个模板变量必须在 Parameters 声明;
  Parameters 每个声明必须出现在 Location 中。
* R09 (structure × structure): Parameters.Type 引用的结构文档必须存在且
  Definition.Form 为 scalar。
* R10 (structure): Form 为 scalar 的结构,Location 必须等于
  ``urn:<namespace>:type:<Name>``。

Matching semantics:

* A ``{var}`` template variable is recognised by the regex
  ``\\{([a-zA-Z_][a-zA-Z0-9_]*)\\}``. R06 normalisation replaces each such
  variable with the literal ``{}`` before comparing Locations globally.
* Locations are ``file:`` or ``urn:`` only — the ``http:`` scheme died in
  generation 2 (Shapes forbids it); http wiring lives on directive edges
  in the component I/O maps (see :mod:`zhizong.graph`).
* R10's namespace is supplied once via :func:`configure_location`, which
  the CLI must call before dispatching rules. A rule raises RuntimeError
  only at the point it actually needs configuration that was never
  supplied — corpora without scalar structures validate fine
  unconfigured.

Documents missing a string ``Location`` (optional for structures since
generation 2; a Shapes.Document finding only for scalar forms, via R10's
urn comparison) are skipped by R06/R07/R08 to avoid double-reporting;
R09 never reads Location; R10 compares the field verbatim, so a scalar
without any Location is reported as not matching the required urn.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from zhizong.graph import directive_edges
from zhizong.registry import Violation, rule, severity_of

if TYPE_CHECKING:
    from zhizong.loader import Corpus

__all__ = [
    "configure_location",
    "http_directive_wiring",
    "parameter_closure",
    "parameter_targets_scalar",
    "scalar_urn_location",
    "unique_normalized_location",
]


_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

_namespace: str | None = None


def configure_location(namespace: str) -> None:
    """Set the urn namespace consumed by R10 (``urn:<ns>:type:<Name>``).

    The CLI must call this once before dispatching rules.
    """

    global _namespace
    _namespace = namespace


def _normalized(location: str) -> str:
    """Location with every ``{var}`` replaced by the literal ``{}``."""

    return _VAR_RE.sub("{}", location)


@rule("R06")
def unique_normalized_location(corpus: Corpus) -> list[Violation]:
    """R06: Locations must be globally unique after template normalisation.

    Every ``{var}`` collapses to ``{}``, so ``file:data/{guild}/x`` and
    ``file:data/{chan}/x`` both normalise to ``file:data/{}/x`` and collide.
    The violation is attributed to the later-loaded structure of a colliding
    pair (first claim wins); the message names both structures.
    """

    severity = severity_of("R06")
    claimed_by: dict[str, str] = {}
    out: list[Violation] = []
    for name, doc in corpus.structures().items():
        location = doc.get("Location")
        if not isinstance(location, str):
            continue
        normalized = _normalized(location)
        if normalized in claimed_by:
            out.append(
                Violation(
                    "R06",
                    name,
                    f"Location {location!r} normalizes to {normalized!r},"
                    f" already claimed by structure {claimed_by[normalized]!r};"
                    " expanded Locations must be globally unique",
                    severity,
                )
            )
        else:
            claimed_by[normalized] = name
    return out


_BRACE_GROUP_RE = re.compile(r"\{([^{}]*)\}")
_VAR_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _path_template_vars(path: str) -> tuple[list[str], list[str]]:
    """Split a directive path's brace groups into (valid names, malformed)."""

    names: list[str] = []
    malformed: list[str] = []
    for raw in _BRACE_GROUP_RE.findall(path):
        if _VAR_NAME_RE.match(raw):
            names.append(raw)
        else:
            malformed.append(raw)
    return names, malformed


@rule("R07")
def http_directive_wiring(corpus: Corpus) -> list[Violation]:
    """R07 (generation 2): directive-path closure and declaration uniqueness.

    One finding per defect, attribution per grammar:
    - path ``{var}`` closure — every identifier-shaped variable of a
      directive path must be declared in the keyed structure's
      Parameters; checked once per unique (structure, directive) pair,
      attributed to the structure. Malformed brace groups are flagged
      alongside; Parameters.Type validity stays R09's job. A structure
      on several directives closes against their union naturally (no
      reverse requirement).
    - verb-direction discipline — GET/DELETE never in a service's
      Upstream (no request-body semantics); attributed to the service.
    - per-service intra-direction uniqueness — one directive under at
      most one structure key per (service, direction).
    - cross-service uniqueness — a (structure, directive, direction)
      triple belongs to at most one service; first claim wins, the later
      service is flagged (claims would otherwise be ambiguous).
    """

    components = corpus.components()
    structures = corpus.structures()
    services = {
        name
        for name, doc in components.items()
        if isinstance(doc, dict) and doc.get("ComponentType") == "service"
    }
    severity = severity_of("R07")
    out: list[Violation] = []

    pairs: dict[tuple[object, str], None] = {}
    intra_seen: dict[tuple[object, str, str], object] = {}
    cross_seen: dict[tuple[object, str, str], object] = {}
    for name, io_field, key, directive in directive_edges(components):
        pairs.setdefault((key, directive))
        method, _, _path = directive.partition(" ")
        if name not in services:
            continue
        if io_field == "Upstream" and method in ("GET", "DELETE"):
            out.append(
                Violation(
                    "R07",
                    name,
                    f"service {name!r} declares {method} directive"
                    f" {directive!r} in Upstream — GET/DELETE carry no"
                    " request body",
                    severity,
                )
            )
        intra_key = (name, io_field, directive)
        if intra_key in intra_seen:
            out.append(
                Violation(
                    "R07",
                    name,
                    f"{name}.{io_field} declares directive {directive!r}"
                    f" under both structures {intra_seen[intra_key]!r} and"
                    f" {key!r}; one route one structure per direction",
                    severity,
                )
            )
        else:
            intra_seen[intra_key] = key
        cross_key = (key, directive, io_field)
        if cross_key in cross_seen:
            out.append(
                Violation(
                    "R07",
                    name,
                    f"directive {directive!r} for structure {key!r} in"
                    f" {io_field} already declared by service"
                    f" {cross_seen[cross_key]!r} — claims would be"
                    " ambiguous",
                    severity,
                )
            )
        else:
            cross_seen[cross_key] = name

    for key, directive in pairs:
        doc = structures.get(key)
        if not isinstance(doc, dict):
            continue  # R20's finding
        params = doc.get("Parameters")
        if not isinstance(params, dict):
            params = {}
        _method, _, path = directive.partition(" ")
        names, malformed = _path_template_vars(path)
        for raw in malformed:
            out.append(
                Violation(
                    "R07",
                    key,
                    f"directive {directive!r} path template variable"
                    f" {{{raw}}} is not a valid identifier",
                    severity,
                )
            )
        for var in names:
            if var not in params:
                out.append(
                    Violation(
                        "R07",
                        key,
                        f"directive {directive!r} path variable"
                        f" {{{var}}} is not declared in Parameters",
                        severity,
                    )
                )
    return out


@rule("R08")
def parameter_closure(corpus: Corpus) -> list[Violation]:
    """R08: ``{var}`` set in Location ≡ Parameters key set, both directions.

    Undeclared Location variables and declared-but-unused Parameters each
    yield their own violation naming the variable.
    """

    severity = severity_of("R08")
    out: list[Violation] = []
    for name, doc in corpus.structures().items():
        location = doc.get("Location")
        if not isinstance(location, str):
            continue
        params = doc.get("Parameters")
        if not isinstance(params, dict):
            params = {}
        used = set(_VAR_RE.findall(location))
        declared = set(params)
        for var in sorted(used - declared):
            out.append(
                Violation(
                    "R08",
                    name,
                    f"Location {location!r} uses template variable {{{var}}}"
                    " not declared in Parameters",
                    severity,
                )
            )
        for var in sorted(declared - used):
            out.append(
                Violation(
                    "R08",
                    name,
                    f"Parameter {var!r} is declared but never used in"
                    f" Location {location!r}",
                    severity,
                )
            )
    return out


@rule("R09")
def parameter_targets_scalar(corpus: Corpus) -> list[Violation]:
    """R09: Parameters.Type must name an existing scalar structure.

    A target that names no structure document in the corpus, or one whose
    ``Definition.Form`` is not ``scalar``, is a violation. Entries without a
    string ``Type`` are left to the shape layer (no double-reporting).
    """

    severity = severity_of("R09")
    structures = corpus.structures()
    out: list[Violation] = []
    for name, doc in structures.items():
        params = doc.get("Parameters")
        if not isinstance(params, dict):
            continue
        for var in sorted(params):
            spec = params[var]
            target = spec.get("Type") if isinstance(spec, dict) else None
            if not isinstance(target, str):
                continue  # malformed entry: Shapes.Document's finding
            if target not in structures:
                out.append(
                    Violation(
                        "R09",
                        name,
                        f"Parameters.{var}.Type references {target!r},"
                        " which is not a structure document in the corpus",
                        severity,
                    )
                )
                continue
            definition = structures[target].get("Definition")
            form = (
                definition.get("Form")
                if isinstance(definition, dict)
                else None
            )
            if form != "scalar":
                out.append(
                    Violation(
                        "R09",
                        name,
                        f"Parameters.{var}.Type references structure"
                        f" {target!r} whose Definition.Form is {form!r},"
                        " not 'scalar'",
                        severity,
                    )
                )
    return out


@rule("R10")
def scalar_urn_location(corpus: Corpus) -> list[Violation]:
    """R10: scalar structures must live at ``urn:<namespace>:type:<Name>``.

    The namespace comes from :func:`configure_location`; ``<Name>`` is the
    structure's own Name. Any other Location (including ``file:``) is a
    violation whose message carries both actual and expected values.
    """

    severity = severity_of("R10")
    out: list[Violation] = []
    for name, doc in corpus.structures().items():
        definition = doc.get("Definition")
        if not (isinstance(definition, dict) and definition.get("Form") == "scalar"):
            continue
        if _namespace is None:
            raise RuntimeError(
                "configure_location() must be called before R10 can build"
                " expected urn addresses"
            )
        expected = f"urn:{_namespace}:type:{name}"
        actual = doc.get("Location")
        if actual != expected:
            out.append(
                Violation(
                    "R10",
                    name,
                    f"scalar structure Location is {actual!r};"
                    f" must be {expected!r}",
                    severity,
                )
            )
    return out
