"""End-to-end CLI for OperantKit sessions."""

from __future__ import annotations

from .cli import main

try:
    from operantkit_cli._version import __version__
except ImportError:
    __version__ = "0.0.0+unknown"
__all__ = ["__version__", "main"]
