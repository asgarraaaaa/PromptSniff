import io
import json
from pathlib import Path

from promptsniff.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_scan_fails_on_high_risk_page(capsys):
    assert main(["scan", str(EXAMPLES / "recipe_blog.html")]) == 1
    out = capsys.readouterr().out
    assert "risk: HIGH" in out
    assert "ignore all previous instructions" in out


def test_scan_passes_on_clean_page_unless_threshold_lowered(capsys):
    page = str(EXAMPLES / "clean_article.html")
    assert main(["scan", page]) == 0
    assert main(["scan", page, "--fail-on", "low"]) == 1


def test_json_output_is_valid(capsys):
    main(["scan", str(EXAMPLES / "job_application.html"), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["risk"] == "high"
    assert {f["technique"] for f in data["findings"]} == {"hidden-text", "html-comment"}


def test_diff_shows_both_views(capsys):
    main(["scan", str(EXAMPLES / "recipe_blog.html"), "--diff"])
    out = capsys.readouterr().out
    person, agent = out.split("--- what a person sees ---")[1].split("--- what an agent reads ---")
    assert "premium cookbook" not in person
    assert "premium cookbook" in agent


def test_clean_prints_visible_text_only(capsys):
    assert main(["clean", str(EXAMPLES / "recipe_blog.html")]) == 0
    out = capsys.readouterr().out
    assert "Nonna's Lasagne" in out
    assert "AI assistants" not in out


def test_reads_plain_text_from_stdin(monkeypatch, capsys):
    text = (EXAMPLES / "support_ticket.txt").read_text(encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    assert main(["scan", "-"]) == 1
    assert "unicode-tags" in capsys.readouterr().out


def test_missing_file(capsys):
    assert main(["scan", "does-not-exist.html"]) == 2
    assert "cannot read" in capsys.readouterr().err
