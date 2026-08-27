"""Location rule tests: R06-R10 — template uniqueness, http wiring,
parameter closure, scalar targets, urn addresses."""

import pytest
import yaml

from zhizong.loader import load_corpus
from zhizong.location import (
    configure_location,
    http_cross_check,
    parameter_closure,
    parameter_targets_scalar,
    scalar_urn_location,
    unique_normalized_location,
)

NAMESPACE = "demo"


@pytest.fixture(autouse=True)
def _configured(tmp_path):
    configure_location(tmp_path, NAMESPACE)


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
        "Location": location,
        "Definition": definition,
    }
    if parameters is not None:
        doc["Parameters"] = parameters
    return doc


def service(name, *, binds="localhost:8080", provides="routes/gateway.txt"):
    return {
        "SchemaVersion": 1,
        "Type": "component",
        "Name": name,
        "Description": f"{name} service",
        "ComponentType": "service",
        "Binds": binds,
        "Provides": provides,
        "Upstream": {},
        "Downstream": {},
        "Runs": f"python -m {name}",
    }


def write_routes(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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


# --- R07: http cross-check against service Binds/Provides routing tables ---


def test_r07_http_hits_single_service_and_path_registered(tmp_path):
    write(tmp_path, "gateway", service("gateway"))
    write_routes(tmp_path, "routes/gateway.txt", "GET /api/feeds\n")
    write(
        tmp_path,
        "snapshot",
        structure("snapshot", "http://localhost:8080/api/feeds"),
    )

    assert http_cross_check(load_corpus(tmp_path)) == []


def test_r07_template_path_variable_matches_raw_location(tmp_path):
    write(
        tmp_path,
        "archive",
        service("archive", provides="routes/archive.txt"),
    )
    write_routes(tmp_path, "routes/archive.txt", "GET /archive/jobs/{id}\n")
    write(
        tmp_path,
        "job",
        structure("job", "http://localhost:8080/archive/jobs/{id}"),
    )

    assert http_cross_check(load_corpus(tmp_path)) == []


def test_r07_comments_and_blank_lines_ignored(tmp_path):
    write(tmp_path, "gateway", service("gateway"))
    write_routes(
        tmp_path,
        "routes/gateway.txt",
        "# gateway routing table\n"
        "\n"
        "   \n"
        "GET /api/feeds\n"
        "# POST /archive/create\n",
    )
    write(
        tmp_path,
        "snapshot",
        structure("snapshot", "http://localhost:8080/api/feeds"),
    )

    assert http_cross_check(load_corpus(tmp_path)) == []


def test_r07_path_not_registered(tmp_path):
    write(tmp_path, "gateway", service("gateway"))
    write_routes(tmp_path, "routes/gateway.txt", "POST /api/other\n")
    write(
        tmp_path,
        "snapshot",
        structure("snapshot", "http://localhost:8080/api/feeds"),
    )

    violations = http_cross_check(load_corpus(tmp_path))

    assert len(violations) == 1
    v = violations[0]
    assert v.rule_id == "R07"
    assert v.doc == "snapshot"
    assert v.severity == "fail"
    assert "/api/feeds" in v.message
    assert "routes/gateway.txt" in v.message


def test_r07_two_services_bind_same_host_port(tmp_path):
    write(tmp_path, "a_gateway", service("gateway"))
    write(tmp_path, "b_gateway2", service("gateway2"))
    write(
        tmp_path,
        "c_snapshot",
        structure("snapshot", "http://localhost:8080/api/feeds"),
    )

    violations = http_cross_check(load_corpus(tmp_path))

    assert len(violations) == 1
    v = violations[0]
    assert v.rule_id == "R07"
    assert v.doc == "snapshot"
    assert "exactly one" in v.message
    assert "gateway" in v.message and "gateway2" in v.message


def test_r07_no_service_binds_host_port(tmp_path):
    write(tmp_path, "gateway", service("gateway"))
    write(
        tmp_path,
        "snapshot",
        structure("snapshot", "http://localhost:9999/api/feeds"),
    )

    violations = http_cross_check(load_corpus(tmp_path))

    assert [v.rule_id for v in violations] == ["R07"]
    assert violations[0].doc == "snapshot"
    assert "localhost:9999" in violations[0].message


def test_r07_provides_routing_file_missing(tmp_path):
    write(
        tmp_path, "gateway", service("gateway", provides="routes/missing.txt")
    )
    write(
        tmp_path,
        "snapshot",
        structure("snapshot", "http://localhost:8080/api/feeds"),
    )

    violations = http_cross_check(load_corpus(tmp_path))

    assert [v.rule_id for v in violations] == ["R07"]
    assert violations[0].doc == "snapshot"
    assert "routes/missing.txt" in violations[0].message


def test_r07_duplicate_path_same_method(tmp_path):
    write(tmp_path, "gateway", service("gateway"))
    write_routes(
        tmp_path,
        "routes/gateway.txt",
        "GET /api/feeds\nGET /api/feeds\n",
    )
    write(
        tmp_path,
        "snapshot",
        structure("snapshot", "http://localhost:8080/api/feeds"),
    )

    violations = http_cross_check(load_corpus(tmp_path))

    assert [v.rule_id for v in violations] == ["R07"]
    v = violations[0]
    assert v.doc == "gateway"
    assert "already registered" in v.message
    assert "line 2" in v.message


def test_r07_duplicate_path_different_method(tmp_path):
    write(tmp_path, "gateway", service("gateway"))
    write_routes(
        tmp_path,
        "routes/gateway.txt",
        "GET /api/feeds\nPOST /api/feeds\n",
    )
    write(
        tmp_path,
        "snapshot",
        structure("snapshot", "http://localhost:8080/api/feeds"),
    )

    violations = http_cross_check(load_corpus(tmp_path))

    assert [v.rule_id for v in violations] == ["R07"]
    v = violations[0]
    assert v.doc == "gateway"
    assert "already registered on line 1 (GET)" in v.message


def test_r07_unknown_method_token(tmp_path):
    write(tmp_path, "gateway", service("gateway"))
    write_routes(
        tmp_path,
        "routes/gateway.txt",
        "GET /api/feeds\nFETCH /api/x\n",
    )
    write(
        tmp_path,
        "snapshot",
        structure("snapshot", "http://localhost:8080/api/feeds"),
    )

    violations = http_cross_check(load_corpus(tmp_path))

    assert [v.rule_id for v in violations] == ["R07"]
    v = violations[0]
    assert v.doc == "gateway"
    assert "line 2" in v.message
    assert "FETCH" in v.message
    assert "routes/gateway.txt" in v.message


def test_r07_path_not_starting_with_slash(tmp_path):
    write(tmp_path, "gateway", service("gateway"))
    write_routes(tmp_path, "routes/gateway.txt", "GET api/feeds\n")
    write(
        tmp_path,
        "snapshot",
        structure("snapshot", "http://localhost:8080/api/feeds"),
    )

    violations = http_cross_check(load_corpus(tmp_path))

    assert [v.rule_id for v in violations] == ["R07"]
    v = violations[0]
    assert v.doc == "gateway"
    assert "line 1" in v.message
    assert "must start with '/'" in v.message


def test_r07_trailing_content_after_path(tmp_path):
    write(tmp_path, "gateway", service("gateway"))
    write_routes(tmp_path, "routes/gateway.txt", "GET /api/feeds y\n")
    write(
        tmp_path,
        "snapshot",
        structure("snapshot", "http://localhost:8080/api/feeds"),
    )

    violations = http_cross_check(load_corpus(tmp_path))

    assert [v.rule_id for v in violations] == ["R07"]
    v = violations[0]
    assert v.doc == "gateway"
    assert "line 1" in v.message
    assert "trailing content" in v.message


def test_r07_route_without_path_token(tmp_path):
    write(tmp_path, "gateway", service("gateway"))
    write_routes(tmp_path, "routes/gateway.txt", "GET\n")
    write(
        tmp_path,
        "snapshot",
        structure("snapshot", "http://localhost:8080/api/feeds"),
    )

    violations = http_cross_check(load_corpus(tmp_path))

    assert [v.rule_id for v in violations] == ["R07"]
    v = violations[0]
    assert v.doc == "gateway"
    assert "line 1" in v.message
    assert "missing its path token" in v.message


def test_r07_routing_table_errors_reported_once_per_service(tmp_path):
    write(tmp_path, "gateway", service("gateway"))
    write_routes(tmp_path, "routes/gateway.txt", "FETCH /api/x\n")
    write(
        tmp_path,
        "a_snap1",
        structure("snap1", "http://localhost:8080/api/feeds"),
    )
    write(
        tmp_path,
        "b_snap2",
        structure("snap2", "http://localhost:8080/api/other"),
    )

    violations = http_cross_check(load_corpus(tmp_path))

    assert [v.doc for v in violations] == ["gateway"]
    assert all(v.rule_id == "R07" for v in violations)


def test_r07_openapi_yaml_provides_is_now_a_parse_violation(tmp_path):
    write(
        tmp_path, "gateway", service("gateway", provides="specs/gateway.yaml")
    )
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "gateway.yaml").write_text(
        "openapi: 3.1.0\n"
        "info:\n"
        "  title: gateway\n"
        "paths:\n"
        "  /api/feeds:\n"
        "    get:\n"
        "      responses:\n"
        "        '200':\n"
        "          description: ok\n",
        encoding="utf-8",
    )
    write(
        tmp_path,
        "snapshot",
        structure("snapshot", "http://localhost:8080/api/feeds"),
    )

    violations = http_cross_check(load_corpus(tmp_path))

    assert violations
    assert all(v.rule_id == "R07" for v in violations)
    assert all(v.doc == "gateway" for v in violations)
    assert any("line" in v.message for v in violations)
    assert "specs/gateway.yaml" in violations[0].message


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

    configure_location(tmp_path, "other")
    assert scalar_urn_location(load_corpus(tmp_path)) == []

    configure_location(tmp_path, NAMESPACE)
    violations = scalar_urn_location(load_corpus(tmp_path))
    assert [v.doc for v in violations] == ["GuildId"]
