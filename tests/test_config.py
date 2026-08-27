"""Config loader tests: key recognition and value semantics."""

import pytest
import yaml

from zhizong.config import ConfigError, load_config

NAMESPACE = "prometheus"


def write_config(tmp_path, doc):
    path = tmp_path / ".zhizong.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def test_minimal_config_defaults(tmp_path):
    path = write_config(tmp_path, {"namespace": NAMESPACE})

    config = load_config(path)

    assert config["namespace"] == NAMESPACE
    assert config["contracts_root"] == "contracts"
    assert config["data_root"] is None


def test_explicit_path_allows_config_discovery(tmp_path):
    path = write_config(tmp_path / "elsewhere", {"namespace": NAMESPACE})

    config = load_config(path)

    assert config["namespace"] == NAMESPACE


def test_data_root_key_accepted_and_honored(tmp_path):
    path = write_config(
        tmp_path, {"namespace": NAMESPACE, "data_root": "archives-tree"}
    )

    config = load_config(path)

    assert config["data_root"] == "archives-tree"


def test_data_root_absolute_path_accepted(tmp_path):
    path = write_config(
        tmp_path, {"namespace": NAMESPACE, "data_root": str(tmp_path / "data")}
    )

    config = load_config(path)

    assert config["data_root"] == str(tmp_path / "data")


def test_data_root_non_string_rejected(tmp_path):
    path = write_config(tmp_path, {"namespace": NAMESPACE, "data_root": 123})

    with pytest.raises(ConfigError, match="data_root"):
        load_config(path)


def test_data_root_empty_string_rejected(tmp_path):
    path = write_config(tmp_path, {"namespace": NAMESPACE, "data_root": ""})

    with pytest.raises(ConfigError, match="data_root"):
        load_config(path)


def test_data_root_not_reported_as_unknown_key(tmp_path):
    path = write_config(
        tmp_path, {"namespace": NAMESPACE, "data_root": "some-tree"}
    )

    config = load_config(path)

    assert config["data_root"] == "some-tree"


def test_unknown_key_still_rejected(tmp_path):
    path = write_config(tmp_path, {"namespace": NAMESPACE, "bogus_key": 1})

    with pytest.raises(ConfigError, match="bogus_key"):
        load_config(path)


def test_missing_config_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="config file not found"):
        load_config(None)


def test_bad_namespace_rejected(tmp_path):
    path = write_config(tmp_path, {"namespace": "Bad Name!"})

    with pytest.raises(ConfigError, match="namespace"):
        load_config(path)


def test_non_mapping_document_rejected(tmp_path):
    path = tmp_path / ".zhizong.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="mapping"):
        load_config(path)
