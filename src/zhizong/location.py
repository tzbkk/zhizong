"""Location invariants R06-R10: template uniqueness, http wiring,
parameter closure, scalar parameter targets, and urn addressing.

Grammar statements (``zhizong/versions/1.yaml``, Definition.Invariants):

* R06 (structure × structure): Location 模板展开后全局唯一。
* R07 (structure × component): Location 为 http 时,host:port 必须命中恰一个
  service 的 Binds,path 必须在该 service 的 Provides 规格 paths 内。
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
* R07 binds matching is exact string equality between the Location's
  netloc (``host:port`` per stdlib ``urllib.parse``) and the service's
  ``Binds`` value — no host canonicalisation (``0.0.0.0`` ≠ ``localhost``).
  The Location's raw path component (template variables left in place,
  matching OpenAPI path templating) must be a key of the spec's ``paths``.

Degraded OpenAPI semantics (W4 scope): a service's ``Provides`` is a plain
string naming an OpenAPI spec FILE, resolved as a path relative to the
configured contracts root. R07 checks, in order: (a) the file exists,
(b) it is YAML-parseable, (c) its parsed root carries a top-level ``paths``
mapping, (d) the Location's path is a key in it. Full OpenAPI 3.1
validation is explicitly out of scope.

Configuration: R07 needs the contracts root to resolve Provides spec files
and R10 needs the urn namespace. Both are supplied once via
:func:`configure_location`, which the CLI (T7) MUST call before dispatching
rules. A rule raises RuntimeError only at the point it actually needs
configuration that was never supplied — corpora without http Locations or
scalar structures validate fine unconfigured.

Documents missing a string ``Location`` (a Shapes.Document finding:
``Location`` is required on structures) are skipped by R06/R07/R08 to avoid
double-reporting; R09 never reads Location; R10 compares the field
verbatim, so a scalar without any Location is reported as not matching the
required urn.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import yaml

from zhizong.registry import Violation, rule, severity_of

if TYPE_CHECKING:
    from zhizong.loader import Corpus

__all__ = [
    "configure_location",
    "http_cross_check",
    "parameter_closure",
    "parameter_targets_scalar",
    "scalar_urn_location",
    "unique_normalized_location",
]


_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

_contracts_root: Path | None = None
_namespace: str | None = None


def configure_location(contracts_root: Path, namespace: str) -> None:
    """Set the module configuration consumed by R07 and R10.

    contracts_root: root under which R07 resolves a service's ``Provides``
        spec-file path (relative paths are joined onto this root).
    namespace: urn namespace for R10's expected scalar addresses
        (``urn:<namespace>:type:<Name>``).

    The CLI (T7) MUST call this once before dispatching rules.
    """

    global _contracts_root, _namespace
    _contracts_root = Path(contracts_root)
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


_SPEC_RESULT_ERROR = tuple[None, str]
_SPEC_RESULT_PATHS = tuple[dict, None]
SpecResult = _SPEC_RESULT_ERROR | _SPEC_RESULT_PATHS


def _spec_paths(provides: str, cache: dict) -> SpecResult:
    """Resolve a Provides spec file → ``(paths mapping, None)`` on success or
    ``(None, error message)`` on failure (degraded W4 semantics: existence,
    YAML-parseability, top-level ``paths`` mapping — nothing more).
    """

    if _contracts_root is None:
        raise RuntimeError(
            "configure_location() must be called before R07 can"
            " resolve Provides spec files"
        )
    spec_path = _contracts_root / provides
    key = str(spec_path)
    if key not in cache:
        if not spec_path.is_file():
            cache[key] = (
                None,
                (
                    f"Provides spec {provides!r} not found under the contracts"
                    f" root ({spec_path})"
                ),
            )
        else:
            try:
                parsed = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
            except (yaml.YAMLError, OSError) as exc:
                cache[key] = (
                    None,
                    f"Provides spec {provides!r} is not YAML-parseable: {exc}",
                )
            else:
                paths = (
                    parsed.get("paths") if isinstance(parsed, dict) else None
                )
                if not isinstance(paths, dict):
                    cache[key] = (
                        None,
                        (
                            f"Provides spec {provides!r} has no top-level"
                            " 'paths' mapping"
                        ),
                    )
                else:
                    cache[key] = (paths, None)
    return cache[key]


@rule("R07")
def http_cross_check(corpus: Corpus) -> list[Violation]:
    """R07: http Locations must be wired to exactly one service.

    For a Location starting ``http:``: its netloc (``host:port``) must equal
    exactly one service component's ``Binds``; the Location's path must then
    be a key in that service's ``Provides`` spec ``paths`` (degraded W4
    semantics — see module docstring).
    """

    severity = severity_of("R07")
    services = {
        name: doc
        for name, doc in corpus.components().items()
        if isinstance(doc, dict) and doc.get("ComponentType") == "service"
    }
    spec_cache: dict = {}
    out: list[Violation] = []
    for name, doc in corpus.structures().items():
        location = doc.get("Location")
        if not (isinstance(location, str) and location.startswith("http:")):
            continue
        parts = urlparse(location)
        matches = sorted(
            n for n, d in services.items() if d.get("Binds") == parts.netloc
        )
        if not matches:
            out.append(
                Violation(
                    "R07",
                    name,
                    f"http Location {location!r}: host:port"
                    f" {parts.netloc!r} does not hit any service's Binds",
                    severity,
                )
            )
            continue
        if len(matches) > 1:
            out.append(
                Violation(
                    "R07",
                    name,
                    f"http Location {location!r}: host:port"
                    f" {parts.netloc!r} hits Binds of {len(matches)}"
                    f" services ({', '.join(matches)}); must hit exactly one",
                    severity,
                )
            )
            continue
        provides = services[matches[0]].get("Provides")
        if not isinstance(provides, str) or not provides:
            continue  # missing/empty Provides is a Shapes.Document finding
        paths, error = _spec_paths(provides, spec_cache)
        if paths is None:
            out.append(
                Violation(
                    "R07",
                    name,
                    f"http Location {location!r} via service"
                    f" {matches[0]!r}: {error}",
                    severity,
                )
            )
            continue
        if parts.path not in paths:
            out.append(
                Violation(
                    "R07",
                    name,
                    f"http Location {location!r}: path {parts.path!r} is"
                    f" not among the paths of service {matches[0]!r}'s"
                    f" Provides spec {provides!r}",
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
