"""CLI subprocess tests: exit-code contract 0/1/2, --version, config errors."""

import subprocess
import sys

import yaml

NAMESPACE = "prometheus"


def run_cli(cwd, *args):
    return subprocess.run(
        [sys.executable, "-m", "zhizong", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def write_yaml(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def build_green_corpus(root):
    """A minimal REAL corpus: service + cli components, three structures,
    a routing table, sample pairs, and the R11 fixture tree."""

    contracts = root / "contracts"
    write_yaml(root / ".zhizong.yaml", {"namespace": NAMESPACE})
    write_yaml(
        contracts / "svc.yaml",
        {
            "SchemaVersion": 1,
            "Type": "component",
            "Name": "svc",
            "Description": "feed api service",
            "ComponentType": "service",
            "Binds": "127.0.0.1:9420",
            "Provides": "routes/svc.txt",
            "Upstream": {"feed": []},
            "Downstream": {"api": ["cli"]},
            "Runs": "python -m svc",
        },
    )
    write_yaml(
        contracts / "cli.yaml",
        {
            "SchemaVersion": 1,
            "Type": "component",
            "Name": "cli",
            "Description": "feed archiver cli",
            "ComponentType": "cli",
            "Upstream": {"api": ["svc"]},
            "Downstream": {"feed": []},
            "Runs": "python -m cli",
        },
    )
    write_yaml(
        contracts / "feed.yaml",
        {
            "SchemaVersion": 1,
            "Type": "structure",
            "Name": "feed",
            "Description": "feed records",
            "Location": "file:data/{guild}/feeds.jsonl",
            "Parameters": {"guild": {"Type": "guildid"}},
            "Definition": {
                "Form": "record",
                "Table": [
                    {
                        "Field": "id",
                        "Type": "string",
                        "Required": True,
                        "Description": "feed id",
                    }
                ],
            },
        },
    )
    write_yaml(
        contracts / "api.yaml",
        {
            "SchemaVersion": 1,
            "Type": "structure",
            "Name": "api",
            "Description": "feed api response",
            "Location": "http://127.0.0.1:9420/api/feed",
            "Definition": {
                "Form": "record",
                "Table": [
                    {
                        "Field": "code",
                        "Type": "integer",
                        "Required": True,
                        "Description": "http status",
                    }
                ],
            },
        },
    )
    write_yaml(
        contracts / "guildid.yaml",
        {
            "SchemaVersion": 1,
            "Type": "structure",
            "Name": "guildid",
            "Description": "guild id scalar",
            "Location": f"urn:{NAMESPACE}:type:guildid",
            "Definition": {"Form": "scalar", "Base": "string", "Pattern": "^[0-9]+$"},
        },
    )
    routes = contracts / "routes" / "svc.txt"
    routes.parent.mkdir(parents=True, exist_ok=True)
    routes.write_text("GET /api/feed\n", encoding="utf-8")

    samples = contracts / "samples"
    samples.mkdir(parents=True, exist_ok=True)
    (samples / "feed.valid.jsonl").write_text('{"id": "f1"}\n', encoding="utf-8")
    (samples / "feed.invalid.jsonl").write_text('{"ts": 1}\n', encoding="utf-8")
    (samples / "api.valid.json").write_text('{"code": 200}\n', encoding="utf-8")
    (samples / "api.invalid.json").write_text('{"code": "ok"}\n', encoding="utf-8")

    fixture = contracts / "fixtures" / "data" / "7743321643036658" / "feeds.jsonl"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text("", encoding="utf-8")
    return root


# --- exit code 0: clean corpus and empty corpus ---


def test_validate_clean_corpus_exits_zero(tmp_path):
    build_green_corpus(tmp_path)

    result = run_cli(tmp_path, "validate")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "5 document(s), 0 violation(s) (0 fail, 0 warn)" in result.stdout


def test_validate_missing_contracts_root_is_empty_corpus_exit_zero(tmp_path):
    write_yaml(
        tmp_path / ".zhizong.yaml",
        {"namespace": NAMESPACE, "contracts_root": "missing_dir"},
    )

    result = run_cli(tmp_path, "validate")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 document(s), 0 violation(s) (0 fail, 0 warn)" in result.stdout


# --- exit code 1: fail-severity violations ---


def test_validate_edge_asymmetry_exits_one(tmp_path):
    build_green_corpus(tmp_path)
    write_yaml(
        tmp_path / "contracts" / "cli.yaml",
        {
            "SchemaVersion": 1,
            "Type": "component",
            "Name": "cli",
            "Description": "feed archiver cli",
            "ComponentType": "cli",
            "Upstream": {"api": ["cli"]},
            "Downstream": {"feed": []},
            "Runs": "python -m cli",
        },
    )

    result = run_cli(tmp_path, "validate")

    assert result.returncode == 1
    assert "[R01]" in result.stdout
    assert "2 violation(s) (2 fail, 0 warn)" in result.stdout


# --- exit code 2: usage and configuration errors ---


def test_validate_bad_namespace_exits_two(tmp_path):
    write_yaml(
        tmp_path / ".zhizong.yaml",
        {"namespace": "Bad Name!", "contracts_root": "contracts"},
    )

    result = run_cli(tmp_path, "validate")

    assert result.returncode == 2
    assert result.stderr.strip() != ""


def test_validate_no_config_anywhere_exits_two(tmp_path):
    result = run_cli(tmp_path, "validate")

    assert result.returncode == 2
    assert result.stderr.strip() != ""


def test_no_arguments_is_usage_error_exit_two(tmp_path):
    result = run_cli(tmp_path)

    assert result.returncode == 2
    assert result.stderr.strip() != ""


# --- data_root config key and --data-root flag (R12 wiring) ---


def build_data_tree(root, *relpaths):
    for rel in relpaths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    return root


def test_validate_config_data_root_drives_r12(tmp_path):
    build_green_corpus(tmp_path)
    dirty = build_data_tree(
        tmp_path / "dirty", "data/7743321643036658/extra.txt"
    )
    write_yaml(
        tmp_path / ".zhizong.yaml",
        {"namespace": NAMESPACE, "data_root": str(dirty)},
    )

    result = run_cli(tmp_path, "validate")

    assert result.returncode == 1
    assert "[R12]" in result.stdout


def test_validate_data_root_flag_overrides_config(tmp_path):
    build_green_corpus(tmp_path)
    dirty = build_data_tree(
        tmp_path / "dirty", "data/7743321643036658/extra.txt"
    )
    clean = build_data_tree(
        tmp_path / "clean", "data/7743321643036658/feeds.jsonl"
    )
    write_yaml(
        tmp_path / ".zhizong.yaml",
        {"namespace": NAMESPACE, "data_root": str(dirty)},
    )

    result = run_cli(tmp_path, "validate", "--data-root", str(clean))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[R12]" not in result.stdout
    assert "0 violation(s) (0 fail, 0 warn)" in result.stdout


def test_validate_data_root_flag_alone_activates_r12(tmp_path):
    build_green_corpus(tmp_path)
    dirty = build_data_tree(
        tmp_path / "dirty", "data/7743321643036658/extra.txt"
    )

    result = run_cli(tmp_path, "validate", "--data-root", str(dirty))

    assert result.returncode == 1
    assert "[R12]" in result.stdout


def test_validate_config_data_root_missing_dir_is_silent(tmp_path):
    build_green_corpus(tmp_path)
    write_yaml(
        tmp_path / ".zhizong.yaml",
        {
            "namespace": NAMESPACE,
            "data_root": str(tmp_path / "no-such-tree"),
        },
    )

    result = run_cli(tmp_path, "validate")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[R12]" not in result.stdout
    assert "0 violation(s) (0 fail, 0 warn)" in result.stdout


def test_validate_data_root_flag_missing_dir_is_silent(tmp_path):
    build_green_corpus(tmp_path)

    result = run_cli(
        tmp_path, "validate", "--data-root", str(tmp_path / "no-such-tree")
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[R12]" not in result.stdout
    assert "0 violation(s) (0 fail, 0 warn)" in result.stdout


# --- --version ---


def test_version_prints_package_version(tmp_path):
    from zhizong import __version__

    result = run_cli(tmp_path, "--version")

    assert result.returncode == 0
    assert result.stdout.strip() == __version__
    assert __version__ == "0.1.1"
