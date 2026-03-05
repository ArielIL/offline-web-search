"""Offline Search — drop-in replacement for web search in air-gapped environments."""

try:
    from ._version import __version__
except ImportError:
    __version__ = "0.0.0+unknown"  # Fallback for editable installs without VCS
