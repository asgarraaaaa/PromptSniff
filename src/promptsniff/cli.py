"""Command line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

from promptsniff import __version__, smuggling
from promptsniff.scan import SEVERITIES, Report, clean, scan, scan_text

MAX_DOWNLOAD = 5 * 1024 * 1024
_COLOURS = {"high": "\033[1;31m", "medium": "\033[33m", "low": "\033[36m", "none": "\033[32m"}
_DIM, _BOLD, _RESET = "\033[2m", "\033[1m", "\033[0m"


def read_source(source: str) -> tuple[str, bool]:
    """Return (content, looks_like_html) for a path, URL, or '-' for stdin."""
    if source == "-":
        content = sys.stdin.read()
    elif source.startswith(("http://", "https://")):
        request = urllib.request.Request(source, headers={"User-Agent": f"promptsniff/{__version__}"})
        with urllib.request.urlopen(request, timeout=15) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            content = response.read(MAX_DOWNLOAD).decode(charset, errors="replace")
    else:
        content = Path(source).read_text(encoding="utf-8", errors="replace")
    suffix = Path(source).suffix.lower()
    is_html = suffix in (".html", ".htm") or (suffix not in (".txt", ".md", ".json") and "<" in content)
    return content, is_html


def render(report: Report, source: str, colour: bool, show_agent_view: bool) -> str:
    def paint(text: str, style: str) -> str:
        return f"{style}{text}{_RESET}" if colour else text

    risk = report.risk
    summary = ", ".join(f"{report.count(s)} {s}" for s in reversed(SEVERITIES) if report.count(s))
    lines = [
        f"{paint('promptsniff', _BOLD)} · {source}",
        f"risk: {paint(risk.upper(), _COLOURS[risk])}" + (f"  ({summary})" if summary else ""),
        "",
    ]
    for f in report.findings:
        tag = paint(f"{f.severity.upper():>6}", _COLOURS[f.severity])
        lines.append(f"{tag}  {f.technique}  {paint(f'line {f.line} · {f.location}', _DIM)}")
        lines.append(f"        {f.detail}")
        if f.text:
            lines.append(f'        "{f.text}"')
        if f.intent_reasons:
            lines.append(paint(f"        reads as AI instructions: {'; '.join(f.intent_reasons)}", _DIM))
        lines.append("")
    if not report.findings:
        lines.append("Nothing hidden found. What you see is what the agent reads.")
    if show_agent_view:
        lines += [paint("--- what a person sees ---", _BOLD), report.visible_text, ""]
        lines += [paint("--- what an agent reads ---", _BOLD), report.agent_text, ""]
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="promptsniff",
        description="Find prompt injections hidden from humans but visible to AI agents.",
    )
    parser.add_argument("--version", action="version", version=f"promptsniff {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_cmd = sub.add_parser("scan", help="report hidden content")
    scan_cmd.add_argument("source", help="file path, http(s) URL, or - for stdin")
    scan_cmd.add_argument("--json", action="store_true", help="machine-readable output")
    scan_cmd.add_argument("--diff", action="store_true", help="also print what a person sees vs. what an agent reads")
    scan_cmd.add_argument(
        "--fail-on",
        choices=SEVERITIES,
        default="high",
        help="exit with status 1 at or above this severity (default: high)",
    )

    clean_cmd = sub.add_parser("clean", help="print only the text a person would see")
    clean_cmd.add_argument("source", help="file path, http(s) URL, or - for stdin")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        content, is_html = read_source(args.source)
    except (OSError, ValueError) as e:
        print(f"promptsniff: cannot read {args.source}: {e}", file=sys.stderr)
        return 2

    if args.command == "clean":
        sys.stdout.write((clean(content) if is_html else smuggling.strip(content)) + "\n")
        return 0

    report = scan(content) if is_html else scan_text(content)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        use_colour = sys.stdout.isatty() and "NO_COLOR" not in os.environ
        sys.stdout.write(render(report, args.source, use_colour, args.diff))

    threshold = SEVERITIES.index(args.fail_on)
    failed = any(SEVERITIES.index(f.severity) >= threshold for f in report.findings)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
