"""Zhizong contract validation tool."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

try:
    # Version comes from installed distribution metadata, never a
    # hand-copied constant (0.2.0 shipped reporting 0.1.1).
    __version__ = _dist_version("zhizong")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"
