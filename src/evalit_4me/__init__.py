"""evalit-4me: 5-layer AI evaluation framework for academic peer review."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("evalit-4me")
except PackageNotFoundError:
    __version__ = "0.0.0+local"

__all__ = ["__version__"]
