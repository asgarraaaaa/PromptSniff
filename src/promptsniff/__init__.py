"""Finds prompt injections hidden in web pages."""

__version__ = "0.1.0"

from promptsniff.scan import Finding, Report, clean, scan, scan_text  # noqa: E402

__all__ = ["Finding", "Report", "clean", "scan", "scan_text"]
