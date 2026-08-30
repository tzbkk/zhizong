"""Location rule tests: R06-R10 — template uniqueness, directive wiring,
parameter closure, scalar targets, urn addresses."""

import pytest
import yaml

from zhizong.loader import load_corpus
from zhizong.location import (
    configure_location,
    http_directive_wiring,
    parameter_closure,
    parameter_targets_scalar,
    scalar_urn_location,
    unique_normalized_location,
)

NAMESPACE = "demo"


@pytest.fixture(autouse=True)
def _configured():
    configure_location(NAMESPACE)


def write(root, filename, doc):
    path = root / f"{filename}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def structure(name, location, *, form="record", parameters=None):
    definition: dict = {"Form": form}
    if form == "record":
        definition["Table"] = [
            {"Field": "id", "Type": "string", "Description": "record id"}
        ]
    elif form == "scalar":
        definition["Base"] = "string"
        definition["Pattern"] = r"^\d+$"
    doc = {
        "SchemaVersion": 1,
        "Type": "structure",
        "Name": name,
        "Description": f"{name} records",
        "Definition": definition,
    }
    if location is not None:
        doc["Location"] = location
    if parameters is not None:
        doc["Parameters"] = parameters
    return doc


def service(name, *, binds="localhost:8080", upstream=None, downstream=None):
    return {
        "SchemaVersion": 1,
        "Type": "component",
        "Name": name,
        "Description": f"{name} service",
        "ComponentType": "service",
        "Binds": binds,
        "Upstream": upstream or {},
        "Downstream": downstream or {},
        "Runs": f"python -m {name}",
    }


def consumer(name, *, upstream=None, downstream=None, ctype="cli"):
    return {
        "SchemaVersion": 1,
        "Type": "component",
        "Name": name,
        "Description": f"{name} {ctype}",
        "ComponentType": ctype,
        "Upstream": upstream or {},
        "Downstream": downstream or {},
        "Runs": name,
    }


# --- R06: uniqueness after template normalization ---


def test_r06_distinct_locations_pass(tmp_path):
    write(tmp_path, "a_feeds", structure("feeds", "file:data/{guild}/feeds.jsonl"))
    write(
        tmp_path,
        "b_comments",
        structure("comments", "file:data/{guild}/comments.jsonl"),
    )

    assert unique_normalized_location(load_corpus(tmp_path)) == []


def test_r06_template_normalization_collision(tmp_path):
    write(tmp_path, "a_chan_x", structure("chanX", "file:data/{chan}/x.jsonl"))
    write(tmp_path, "b_guild_x", structure("guildX", "file:data/{guild}/x.jsonl"))

    violations = unique_normalized_location(load_corpus(tmp_path))

    assert len(violations) == 1
    v = violations[0]
    assert v.rule_id == "R06"
    assert v.doc == "guildX"
    assert v.severity == "fail"
    assert "file:data/{}/x.jsonl" in v.message
    assert "chanX" in v.message


# --- R07: directive wiring — closure, verb discipline, uniqueness ---


def test_r07_path_variable_declared_passes(tmp_path):
    write(
        tmp_path,
        "archive",
        service("archive", downstream={"Job": "GET /archive/jobs/{id}"}),
    )
    write(
        tmp_path,
        "job",
        structure("Job", None, parameters={"id": {"Type": "JobId"}}),
    )

    assert http_directive_wiring(load_corpus(tmp_path)) == []


def test_r07_path_variable_not_declared_in_parameters(tmp_path):
    write(
        tmp_path,
        "archive",
        service("archive", downstream={"Job": "GET /archive/jobs/{id}"}),
    )
    write(tmp_path, "job", structure("Job", None))

    violations = http_directive_wiring(load_corpus(tmp_path))

    assert len(violations) == 1
    v = violations[0]
    assert v.rule_id == "R07"
    assert v.doc == "Job"
    assert v.severity == "fail"
    assert "{id}" in v.message
    assert "Parameters" in v.message


def test_r07_malformed_variable_name_flagged(tmp_path):
    write(
        tmp_path,
        "archive",
        service("archive", downstream={"Job": "GET /archive/jobs/{bad-id}"}),
    )
    write(tmp_path, "job", structure("Job", None))

    violations = http_directive_wiring(load_corpus(tmp_path))

    assert [v.rule_id for v in violations] == ["R07"]
    assert violations[0].doc == "Job"
    assert "{bad-id}" in violations[0].message
    assert "identifier" in violations[0].message


def test_r07_static_path_needs_no_parameters(tmp_path):
    write(
        tmp_path,
        "archive",
        service("archive", downstream={"List": "GET /archive/guilds"}),
    )
    write(tmp_path, "list", structure("List", None))

    assert http_directive_wiring(load_corpus(tmp_path)) == []


def test_r07_get_in_service_upstream_rejected(tmp_path):
    write(
        tmp_path,
        "archive",
        service("archive", upstream={"Job": "GET /archive/jobs"}),
    )
    write(tmp_path, "job", structure("Job", None))

    violations = http_directive_wiring(load_corpus(tmp_path))

    assert [v.rule_id for v in violations] == ["R07"]
    v = violations[0]
    assert v.doc == "archive"
    assert "GET" in v.message
    assert "no request body" in v.message


def test_r07_delete_in_service_upstream_rejected(tmp_path):
    write(
        tmp_path,
        "archive",
        service("archive", upstream={"Gone": "DELETE /archive/jobs"}),
    )
    write(tmp_path, "gone", structure("Gone", None))

    violations = http_directive_wiring(load_corpus(tmp_path))

    assert [v.rule_id for v in violations] == ["R07"]
    assert violations[0].doc == "archive"
    assert "DELETE" in violations[0].message


def test_r07_post_in_service_upstream_is_request_body(tmp_path):
    write(
        tmp_path,
        "archive",
        service(
            "archive",
            upstream={"CreateJobRequest": "POST /archive/create"},
            downstream={"JobCreated": "POST /archive/create"},
        ),
    )
    write(tmp_path, "req", structure("CreateJobRequest", None))
    write(tmp_path, "resp", structure("JobCreated", None))

    assert http_directive_wiring(load_corpus(tmp_path)) == []


def test_r07_bidirectional_payload_allowed(tmp_path):
    write(
        tmp_path,
        "launcher",
        service(
            "launcher",
            upstream={"Config": "PUT /config"},
            downstream={"Config": "PUT /config"},
        ),
    )
    write(tmp_path, "config", structure("Config", None))

    assert http_directive_wiring(load_corpus(tmp_path)) == []


def test_r07_one_directive_two_keys_same_direction_rejected(tmp_path):
    write(
        tmp_path,
        "archive",
        service(
            "archive",
            downstream={
                "JobA": "GET /archive/jobs",
                "JobB": "GET /archive/jobs",
            },
        ),
    )
    write(tmp_path, "joba", structure("JobA", None))
    write(tmp_path, "jobb", structure("JobB", None))

    violations = http_directive_wiring(load_corpus(tmp_path))

    assert [v.rule_id for v in violations] == ["R07"]
    v = violations[0]
    assert v.doc == "archive"
    assert "one route one structure" in v.message
    assert "JobA" in v.message and "JobB" in v.message


def test_r07_two_services_same_directive_same_direction_rejected(tmp_path):
    write(
        tmp_path,
        "a_alpha",
        service("alpha", downstream={"List": "GET /shared/list"}),
    )
    write(
        tmp_path,
        "b_beta",
        service("beta", binds="localhost:8081", downstream={"List": "GET /shared/list"}),
    )
    write(tmp_path, "list", structure("List", None))

    violations = http_directive_wiring(load_corpus(tmp_path))

    assert [v.rule_id for v in violations] == ["R07"]
    v = violations[0]
    assert v.doc == "beta"
    assert "alpha" in v.message
    assert "ambiguous" in v.message


def test_r07_two_services_same_directive_opposite_directions_pass(tmp_path):
    write(
        tmp_path,
        "a_alpha",
        service("alpha", upstream={"X": "POST /relay"}),
    )
    write(
        tmp_path,
        "b_beta",
        service("beta", binds="localhost:8081", downstream={"X": "POST /relay"}),
    )
    write(tmp_path, "x", structure("X", None))

    assert http_directive_wiring(load_corpus(tmp_path)) == []


def test_r07_union_closure_across_directives(tmp_path):
    write(
        tmp_path,
        "launcher",
        service(
            "launcher",
            downstream={
                "Config": "GET /config/{section}",
                "Audit": "GET /audit",
            },
        ),
    )
    write(
        tmp_path,
        "config",
        structure("Config", None, parameters={"section": {"Type": "Section"}}),
    )
    write(tmp_path, "audit", structure("Audit", None))

    assert http_directive_wiring(load_corpus(tmp_path)) == []


def test_r07_unresolved_claims_are_r03s_job(tmp_path):
    write(
        tmp_path,
        "tui",
        consumer("tui", upstream={"Ghost": "GET /nowhere"}),
    )
    write(tmp_path, "ghost", structure("Ghost", None))

    assert http_directive_wiring(load_corpus(tmp_path)) == []


def test_r07_missing_structure_key_left_to_r20(tmp_path):
    write(
        tmp_path,
        "archive",
        service("archive", downstream={"NoSuch": "GET /archive/x"}),
    )

    assert http_directive_wiring(load_corpus(tmp_path)) == []


# --- R08: parameter closure, both directions ---


def test_r08_closure_pass(tmp_path):
    params = {"guild": {"Type": "GuildId"}, "chan": {"Type": "ChannelId"}}
    write(
        tmp_path,
        "feeds",
        structure("feeds", "file:data/{guild}/{chan}/feeds.jsonl", parameters=params),
    )

    assert parameter_closure(load_corpus(tmp_path)) == []


def test_r08_undeclared_location_variable(tmp_path):
    params = {"guild": {"Type": "GuildId"}}
    write(
        tmp_path,
        "feeds",
        structure("feeds", "file:data/{guild}/{chan}/feeds.jsonl", parameters=params),
    )

    violations = parameter_closure(load_corpus(tmp_path))

    assert len(violations) == 1
    v = violations[0]
    assert v.rule_id == "R08"
    assert v.doc == "feeds"
    assert v.severity == "fail"
    assert "{chan}" in v.message


def test_r08_declared_but_unused_parameter(tmp_path):
    params = {"guild": {"Type": "GuildId"}, "limit": {"Type": "Limit"}}
    write(
        tmp_path,
        "feeds",
        structure("feeds", "file:data/{guild}/feeds.jsonl", parameters=params),
    )

    violations = parameter_closure(load_corpus(tmp_path))

    assert len(violations) == 1
    v = violations[0]
    assert v.rule_id == "R08"
    assert v.doc == "feeds"
    assert v.severity == "fail"
    assert "limit" in v.message


def test_r08_locationless_structure_skipped(tmp_path):
    write(tmp_path, "job", structure("Job", None, parameters={"id": {"Type": "JobId"}}))

    assert parameter_closure(load_corpus(tmp_path)) == []


# --- R09: Parameters.Type targets must be existing scalar structures ---


def test_r09_scalar_target_pass(tmp_path):
    write(
        tmp_path,
        "a_guild_id",
        structure("GuildId", f"urn:{NAMESPACE}:type:GuildId", form="scalar"),
    )
    params = {"guild": {"Type": "GuildId"}}
    write(
        tmp_path,
        "b_feeds",
        structure(
            "feeds", "file:data/{guild}/feeds.jsonl", parameters=params
        ),
    )

    assert parameter_targets_scalar(load_corpus(tmp_path)) == []


def test_r09_record_target_is_not_scalar(tmp_path):
    write(tmp_path, "a_point", structure("Point", "file:data/points.jsonl"))
    params = {"point": {"Type": "Point"}}
    write(
        tmp_path,
        "b_shapes",
        structure(
            "shapes", "file:data/{point}/shapes.jsonl", parameters=params
        ),
    )

    violations = parameter_targets_scalar(load_corpus(tmp_path))

    assert len(violations) == 1
    v = violations[0]
    assert v.rule_id == "R09"
    assert v.doc == "shapes"
    assert v.severity == "fail"
    assert "Point" in v.message
    assert "record" in v.message


def test_r09_unknown_target(tmp_path):
    params = {"guild": {"Type": "NoSuchScalar"}}
    write(
        tmp_path,
        "feeds",
        structure("feeds", "file:data/{guild}/feeds.jsonl", parameters=params),
    )

    violations = parameter_targets_scalar(load_corpus(tmp_path))

    assert [v.rule_id for v in violations] == ["R09"]
    assert violations[0].doc == "feeds"
    assert "NoSuchScalar" in violations[0].message


# --- R10: scalar structures must use urn:<namespace>:type:<Name> ---


def test_r10_scalar_urn_pass(tmp_path):
    write(
        tmp_path,
        "guild_id",
        structure("GuildId", f"urn:{NAMESPACE}:type:GuildId", form="scalar"),
    )

    assert scalar_urn_location(load_corpus(tmp_path)) == []


def test_r10_scalar_file_location_violation(tmp_path):
    write(
        tmp_path,
        "guild_id",
        structure("GuildId", "file:/data/guild_id.txt", form="scalar"),
    )

    violations = scalar_urn_location(load_corpus(tmp_path))

    assert len(violations) == 1
    v = violations[0]
    assert v.rule_id == "R10"
    assert v.doc == "GuildId"
    assert v.severity == "fail"
    assert "file:/data/guild_id.txt" in v.message
    assert f"urn:{NAMESPACE}:type:GuildId" in v.message


def test_r10_namespace_comes_from_configuration(tmp_path):
    write(
        tmp_path,
        "guild_id",
        structure("GuildId", "urn:other:type:GuildId", form="scalar"),
    )

    configure_location("other")
    assert scalar_urn_location(load_corpus(tmp_path)) == []

    configure_location(NAMESPACE)
    violations = scalar_urn_location(load_corpus(tmp_path))
    assert [v.doc for v in violations] == ["GuildId"]
