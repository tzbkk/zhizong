"""Component I/O graph rules: R01-R05, R17, R20.

Every check follows the registry convention — ``@rule("RXX")`` over a pure
``fn(corpus) -> list[Violation]`` with zero I/O. Reference maps (declared
edges, downstream membership, Parameters.Type targets) are built once per
rule invocation; lookups run against those maps, never via corpus rescans
inside loops.

Attribution conventions (deterministic):
- R01 attributes a violation to the DECLARING side — the component whose
  own Upstream/Downstream list contains the unreciprocated node.
- Nodes naming no existing component are skipped by R01: existence is
  R02's job, so one defect yields one finding, not two.
- ``external:``-prefixed nodes and empty node lists are exempt from
  symmetry checks (grammar NodeSyntax: an empty list means the
  counterparty is the file itself).
- Every other rule attributes to the offending document's Name as keyed
  in ``Corpus.documents``.
"""

from __future__ import annotations

from typing import Any, Iterator

from zhizong.loader import Corpus
from zhizong.registry import Violation, rule, severity_of

EXTERNAL_PREFIX = "external:"


def _is_component_node(node: Any) -> bool:
    return isinstance(node, str) and not node.startswith(EXTERNAL_PREFIX)


def _component_edges(components: dict) -> Iterator[tuple[Any, str, Any, list]]:
    """Stream ``(component, io_field, structure_key, nodes)`` deterministically.

    Shape-invalid io maps (non-dict) and node lists (non-list) stream as
    absent/empty — the shape layer reports those; graph rules stay
    crash-free on pre-shape-validation corpora.
    """

    for name, doc in sorted(components.items(), key=lambda kv: repr(kv[0])):
        for io_field in ("Upstream", "Downstream"):
            io_map = doc.get(io_field) if isinstance(doc, dict) else None
            if not isinstance(io_map, dict):
                continue
            for key, nodes in io_map.items():
                yield name, io_field, key, nodes if isinstance(nodes, list) else []


@rule("R01")
def r01_edge_symmetry(corpus: Corpus) -> list[Violation]:
    """A.Upstream[S] ∋ B ⟺ B.Downstream[S] ∋ A, for component-name nodes.

    Both directions are checked; ``external:`` nodes, empty lists, and
    nodes naming no existing component are exempt.
    """

    components = corpus.components()
    component_names = set(components)
    declared: dict[tuple[Any, str, Any], set] = {}
    for name, io_field, key, nodes in _component_edges(components):
        peers = {
            node
            for node in nodes
            if _is_component_node(node) and node in component_names
        }
        if peers:
            declared[(name, io_field, key)] = peers

    mirror = {"Upstream": "Downstream", "Downstream": "Upstream"}
    out: list[Violation] = []
    for (name, io_field, key), peers in sorted(
        declared.items(), key=lambda item: (repr(item[0][0]), item[0][1], repr(item[0][2]))
    ):
        for peer in sorted(peers, key=repr):
            reciprocal = declared.get((peer, mirror[io_field], key), frozenset())
            if name not in reciprocal:
                out.append(
                    Violation(
                        "R01",
                        name,
                        f"{name}.{io_field}[{key!r}] declares node {peer!r}"
                        f" but {peer}.{mirror[io_field]}[{key!r}]"
                        f" does not list {name!r}",
                        severity_of("R01"),
                    )
                )
    return out


@rule("R02")
def r02_nodes_exist(corpus: Corpus) -> list[Violation]:
    """Component-name nodes must be library components; ``external:`` sources registered."""

    components = corpus.components()
    component_names = set(components)
    externals = corpus.externals if isinstance(corpus.externals, dict) else {}
    out: list[Violation] = []
    for name, io_field, key, nodes in _component_edges(components):
        for node in nodes:
            if not isinstance(node, str):
                continue
            if node.startswith(EXTERNAL_PREFIX):
                source = node[len(EXTERNAL_PREFIX) :]
                if source not in externals:
                    out.append(
                        Violation(
                            "R02",
                            name,
                            f"{name}.{io_field}[{key!r}]: external source"
                            f" {source!r} is not registered in externals.yaml",
                            severity_of("R02"),
                        )
                    )
            elif node not in component_names:
                out.append(
                    Violation(
                        "R02",
                        name,
                        f"{name}.{io_field}[{key!r}]: node {node!r} matches"
                        f" no component in the library",
                        severity_of("R02"),
                    )
                )
    return out


@rule("R03")
def r03_upstream_needs_downstream_counterpart(corpus: Corpus) -> list[Violation]:
    """Non-empty C.Upstream[S] needs some X with C ∈ X.Downstream[S].

    An empty list is legal — the counterparty is the file itself.
    """

    components = corpus.components()
    downstream_members: dict[Any, set] = {}
    for name, io_field, key, nodes in _component_edges(components):
        if io_field != "Downstream":
            continue
        members = downstream_members.setdefault(key, set())
        members.update(node for node in nodes if _is_component_node(node))

    out: list[Violation] = []
    for name, io_field, key, nodes in _component_edges(components):
        if io_field != "Upstream" or not nodes:
            continue
        if name not in downstream_members.get(key, frozenset()):
            out.append(
                Violation(
                    "R03",
                    name,
                    f"{name}.Upstream[{key!r}] lists counterpart nodes but no"
                    f" component lists {name!r} in Downstream[{key!r}]",
                    severity_of("R03"),
                )
            )
    return out


@rule("R04")
def r04_structures_must_be_referenced(corpus: Corpus) -> list[Violation]:
    """A structure unreferenced by any I/O key or Parameters.Type is orphaned.

    Parameters.Type-referenced scalars land in the reference set — that is
    the exemption.
    """

    referenced = _referenced_structure_names(corpus)
    out: list[Violation] = []
    for name in sorted(corpus.structures(), key=repr):
        if name not in referenced:
            out.append(
                Violation(
                    "R04",
                    name,
                    f"structure {name!r} is referenced by no component I/O"
                    f" key and no Parameters.Type",
                    severity_of("R04"),
                )
            )
    return out


def _referenced_structure_names(corpus: Corpus) -> set:
    """All I/O keys ∪ every Parameters.Type target across the corpus."""

    referenced: set = set()
    for _name, _io_field, key, _nodes in _component_edges(corpus.components()):
        referenced.add(key)
    for doc in corpus.documents.values():
        if not isinstance(doc, dict):
            continue
        parameters = doc.get("Parameters")
        if not isinstance(parameters, dict):
            continue
        for parameter in parameters.values():
            if isinstance(parameter, dict) and isinstance(
                parameter.get("Type"), str
            ):
                referenced.add(parameter["Type"])
    return referenced


@rule("R05")
def r05_entrypoint_discipline(corpus: Corpus) -> list[Violation]:
    """Edgeless components must carry ``role: entrypoint``; libraries never may."""

    components = corpus.components()
    with_edges = set()
    for name, _io_field, _key, nodes in _component_edges(components):
        if nodes:
            with_edges.add(name)

    out: list[Violation] = []
    for name in sorted(components, key=repr):
        doc = components[name]
        has_entrypoint_role = doc.get("role") == "entrypoint"
        if name not in with_edges and not has_entrypoint_role:
            out.append(
                Violation(
                    "R05",
                    name,
                    f"component {name!r} declares no edges but is not marked"
                    f" role: entrypoint",
                    severity_of("R05"),
                )
            )
        if doc.get("ComponentType") == "library" and has_entrypoint_role:
            out.append(
                Violation(
                    "R05",
                    name,
                    f"library component {name!r} must not be marked"
                    f" role: entrypoint",
                    severity_of("R05"),
                )
            )
    return out


@rule("R17")
def r17_document_names_unique(corpus: Corpus) -> list[Violation]:
    """Name 库内唯一 — one Violation per duplicate the loader recorded.

    The loader keeps the first occurrence; every repeat lands in
    ``Corpus.duplicate_names`` and is flagged here.
    """

    return [
        Violation(
            "R17",
            name,
            f"document Name {name!r} is not unique in the library"
            f" (first occurrence kept)",
            severity_of("R17"),
        )
        for name in corpus.duplicate_names
    ]


@rule("R20")
def r20_io_keys_resolve_to_structures(corpus: Corpus) -> list[Violation]:
    """Every Upstream/Downstream key must Name-match a structure document."""

    structure_names = set(corpus.structures())
    out: list[Violation] = []
    for name, io_field, key, _nodes in _component_edges(corpus.components()):
        if key not in structure_names:
            out.append(
                Violation(
                    "R20",
                    name,
                    f"{name}.{io_field} key {key!r} matches no structure"
                    f" document Name",
                    severity_of("R20"),
                )
            )
    return out
