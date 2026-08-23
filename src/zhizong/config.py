"""Configuration loading for the zhizong CLI.

Configuration discovery is deliberately minimal: an explicit ``--config PATH``
or ``.zhizong.yaml`` in the current working directory — never a parent
directory traversal. Recognised keys:

* ``namespace`` — REQUIRED, must match ``^[a-z][a-z0-9-]*$``.
* ``contracts_root`` — optional, default ``contracts``; relative to the
  working directory.

``data_root`` is deliberately NOT a recognised key in 0.1.0 (no consumer:
R12 stays dormant until the real-tree pass gains one); a config carrying it
is rejected with a clear message rather than silently ignored.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

__all__ = ["ConfigError", "load_config"]

CONFIG_FILENAME = ".zhizong.yaml"
DEFAULT_CONTRACTS_ROOT = "contracts"
KNOWN_KEYS = frozenset({"namespace", "contracts_root"})

_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class ConfigError(Exception):
    """Invalid configuration: missing file, YAML error, or bad key/value."""


def load_config(path: Path | None) -> dict:
    """Load and validate the CLI configuration.

    path: explicit config file; None means ``<cwd>/.zhizong.yaml``.

    Returns ``{"namespace": str, "contracts_root": str}``; raises
    :class:`ConfigError` for a missing file, a YAML syntax error, a
    non-mapping document, a missing/invalid ``namespace``, a bad
    ``contracts_root``, the deferred ``data_root`` key, or any unknown key.
    """

    config_path = Path(path) if path is not None else Path.cwd() / CONFIG_FILENAME
    if not config_path.is_file():
        raise ConfigError(
            f"config file not found: {config_path}"
            f" (pass --config PATH or create {CONFIG_FILENAME}"
            " in the working directory)"
        )
    try:
        parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{config_path}: YAML parse error: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{config_path}: cannot read file: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ConfigError(
            f"{config_path}: config must be a YAML mapping,"
            f" got {type(parsed).__name__}"
        )
    if "data_root" in parsed:
        raise ConfigError(
            f"{config_path}: key 'data_root' is not supported in 0.1.0"
            " (real-tree validation is deferred by design); remove it"
        )
    if "namespace" not in parsed:
        raise ConfigError(f"{config_path}: required key 'namespace' is missing")
    namespace = parsed["namespace"]
    if not isinstance(namespace, str) or not _NAMESPACE_RE.fullmatch(namespace):
        raise ConfigError(
            f"{config_path}: namespace {namespace!r} must match"
            " ^[a-z][a-z0-9-]*$"
        )
    contracts_root = parsed.get("contracts_root", DEFAULT_CONTRACTS_ROOT)
    if not isinstance(contracts_root, str) or not contracts_root:
        raise ConfigError(
            f"{config_path}: contracts_root must be a non-empty string"
        )
    unknown = sorted(set(parsed) - KNOWN_KEYS)
    if unknown:
        raise ConfigError(
            f"{config_path}: unknown key(s): {', '.join(unknown)}"
            f" (recognised: {', '.join(sorted(KNOWN_KEYS))})"
        )
    return {"namespace": namespace, "contracts_root": contracts_root}
