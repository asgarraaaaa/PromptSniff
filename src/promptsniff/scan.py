"""Compares the text a person sees with the text an agent reads."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from promptsniff import intent, smuggling
from promptsniff.css import (
    RGBA,
    Rule,
    blend,
    cascade,
    colour_from_background,
    contrast_ratio,
    parse_colour,
    parse_length,
    parse_stylesheet,
)
from promptsniff.dom import BLOCK_TAGS, NON_RENDERED_TAGS, Comment, Element, Text, collapse, parse

SEVERITIES = ("low", "medium", "high")
# attributes that agents usually read
READ_ATTRIBUTES = ("alt", "title", "aria-label", "aria-description", "placeholder", "content")
MIN_CONTRAST = 1.15
OFFSCREEN_PX = -500


@dataclass(frozen=True)
class Finding:
    technique: str
    severity: str
    detail: str
    text: str
    location: str
    line: int
    intent_score: float = 0.0
    intent_reasons: tuple[str, ...] = ()


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    visible_text: str = ""
    agent_text: str = ""

    @property
    def risk(self) -> str:
        if not self.findings:
            return "none"
        return max((f.severity for f in self.findings), key=SEVERITIES.index)

    def count(self, severity: str) -> int:
        return sum(f.severity == severity for f in self.findings)

    def to_dict(self) -> dict:
        return {
            "risk": self.risk,
            "findings": [asdict(f) for f in self.findings],
            "visible_text": self.visible_text,
            "agent_text": self.agent_text,
        }


def scan(html: str) -> Report:
    root = parse(html)
    rules: list[Rule] = []
    for node in root.iter():
        if isinstance(node, Element) and node.tag == "style":
            rules.extend(parse_stylesheet(node.text_content(), start_order=len(rules)))
    return _Scanner(rules).run(root)


def scan_text(text: str) -> Report:
    """For plain text (emails, tool results...): only unicode tricks and instructions."""
    report = Report(visible_text=smuggling.strip(text), agent_text=text)
    report.findings.extend(_smuggling_findings(text, "text", 1))
    verdict = intent.analyse(smuggling.strip(text))
    if verdict.is_instruction:
        report.findings.append(
            Finding(
                technique="instructions",
                severity="medium",
                detail="the text gives orders to an AI assistant",
                text=_excerpt(text),
                location="text",
                line=1,
                intent_score=verdict.score,
                intent_reasons=verdict.reasons,
            )
        )
    return report


def clean(html: str) -> str:
    """Only the visible text, without invisible characters."""
    return smuggling.strip(scan(html).visible_text)


@dataclass(frozen=True)
class _Style:
    font_px: float = 16.0
    colour: RGBA = (0, 0, 0, 1.0)
    background: tuple[float, float, float] = (255, 255, 255)
    background_image: bool = False
    visibility_hidden: bool = False
    opacity: float = 1.0
    # display:none, off-screen etc, applies to all children
    box_hidden: str | None = None
    # (kind, reason) and the element where the hiding starts
    hidden: tuple[str, str] | None = None
    origin: Element | None = None


def _compute(el: Element, d: dict[str, str], parent: _Style) -> _Style:
    font_px = parse_length(d["font-size"], parent.font_px) if "font-size" in d else None
    font_px = parent.font_px if font_px is None else font_px

    colour = parse_colour(d["color"]) if "color" in d else None
    colour = colour or parent.colour

    background = parent.background
    background_image = parent.background_image
    bg_value = d.get("background-color") or d.get("background")
    if bg_value:
        bg = colour_from_background(bg_value)
        if bg is not None and bg[3] > 0:
            background = blend(bg, parent.background)
    if any("url(" in d.get(p, "") or "gradient(" in d.get(p, "") for p in ("background", "background-image")):
        background_image = True

    visibility = d.get("visibility")
    visibility_hidden = visibility in ("hidden", "collapse") or (parent.visibility_hidden and visibility != "visible")

    opacity = parent.opacity * _parse_opacity(d.get("opacity", "1"))

    box_hidden = parent.box_hidden or _own_box_hiding(el, d)

    style = _Style(font_px, colour, background, background_image, visibility_hidden, opacity, box_hidden)
    hidden = _why_hidden(style)
    if hidden is None:
        origin = None
    elif parent.hidden is not None and parent.hidden[0] == hidden[0]:
        origin = parent.origin
    else:
        origin = el
    return _Style(font_px, colour, background, background_image, visibility_hidden, opacity, box_hidden, hidden, origin)


def _parse_opacity(value: str) -> float:
    try:
        number = float(value[:-1]) / 100 if value.endswith("%") else float(value)
    except ValueError:
        return 1.0
    return min(1.0, max(0.0, number))


def _own_box_hiding(el: Element, d: dict[str, str]) -> str | None:
    if d.get("display") == "none":
        return "display:none"
    if "hidden" in el.attrs:
        return "hidden attribute"
    if d.get("position") in ("absolute", "fixed"):
        for side in ("left", "top", "right", "bottom"):
            px = parse_length(d.get(side, ""), 16.0)
            if px is not None and px <= OFFSCREEN_PX:
                return f"positioned off-screen ({side}: {d[side]})"
    indent = parse_length(d.get("text-indent", ""), 16.0)
    if indent is not None and indent <= OFFSCREEN_PX:
        return f"pushed off-screen (text-indent: {d['text-indent']})"
    m = re.search(r"translate[xy]?\(\s*(-\d+)px", d.get("transform", ""))
    if m and int(m[1]) <= OFFSCREEN_PX:
        return f"moved off-screen (transform: {d['transform']})"
    if re.fullmatch(r"rect\(\s*(0|1px)[\s,]+(0|1px)[\s,]+(0|1px)[\s,]+(0|1px)\s*\)", d.get("clip", "")):
        return f"clipped away (clip: {d['clip']})"
    if re.match(r"(inset\(\s*50%|circle\(\s*0)", d.get("clip-path", "")):
        return f"clipped away (clip-path: {d['clip-path']})"
    if d.get("overflow") == "hidden":
        w = parse_length(d.get("width", ""), 16.0)
        h = parse_length(d.get("height", ""), 16.0)
        if (w is not None and w <= 1) or (h is not None and h <= 1):
            return "zero-size box with overflow:hidden"
    return None


def _why_hidden(s: _Style) -> tuple[str, str] | None:
    if s.box_hidden:
        return ("box", s.box_hidden)
    if s.visibility_hidden:
        return ("visibility", "visibility:hidden")
    if s.opacity < 0.05:
        return ("opacity", f"opacity: {s.opacity:g}")
    if s.font_px < 2:
        return ("font-size", f"font-size: {s.font_px:g}px")
    if s.colour[3] < 0.05:
        return ("colour", "transparent text")
    if not s.background_image:
        fg = blend(s.colour, s.background)
        ratio = contrast_ratio(fg, s.background)
        if ratio < MIN_CONTRAST:
            return ("colour", f"text colour {_hex(fg)} on background {_hex(s.background)} (contrast {ratio:.2f}:1)")
    return None


def _hex(c: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(v):02x}" for v in c)


class _Scanner:
    def __init__(self, rules: list[Rule]):
        self.rules = rules
        self.findings: list[Finding] = []
        self.visible: list[str] = []
        self.agent: list[str] = []
        self.hidden_groups: dict[Element, list[Text]] = {}
        self.hidden_detail: dict[Element, str] = {}

    def run(self, root: Element) -> Report:
        self._walk(root, _Style(), non_rendered=False)
        for origin, texts in self.hidden_groups.items():
            self._hidden_finding(origin, texts)
        self.findings.sort(key=lambda f: (-SEVERITIES.index(f.severity), f.line))
        return Report(self.findings, collapse("".join(self.visible)), collapse("".join(self.agent)))

    def _walk(self, el: Element, style: _Style, non_rendered: bool) -> None:
        for child in el.children:
            if isinstance(child, Text):
                self._text(child, style, non_rendered)
            elif isinstance(child, Comment):
                self._comment(child)
            else:
                child_style = _compute(child, cascade(child, self.rules), style)
                self._attributes(child)
                block = "\n" if child.tag in BLOCK_TAGS else ""
                self.visible.append(block)
                self.agent.append(block)
                self._walk(child, child_style, non_rendered or child.tag in NON_RENDERED_TAGS)
                self.visible.append(block)
                self.agent.append(block)

    def _text(self, node: Text, style: _Style, non_rendered: bool) -> None:
        location = node.parent.path()
        self.findings.extend(_smuggling_findings(node.text, location, node.line))
        if non_rendered:
            if node.parent.tag in ("script", "style"):
                return
            verdict = intent.analyse(node.text)
            if verdict.is_instruction:
                self.findings.append(
                    Finding(
                        "non-rendered",
                        "high",
                        f"inside <{node.parent.tag}>, which is never shown on the page",
                        _excerpt(node.text),
                        location,
                        node.line,
                        verdict.score,
                        verdict.reasons,
                    )
                )
            return
        self.agent.append(node.text)
        if style.hidden is None or style.origin is None:
            self.visible.append(node.text)
        else:
            self.hidden_groups.setdefault(style.origin, []).append(node)
            self.hidden_detail.setdefault(style.origin, style.hidden[1])

    def _comment(self, node: Comment) -> None:
        verdict = intent.analyse(node.text)
        if verdict.is_instruction:
            self.findings.append(
                Finding(
                    "html-comment",
                    "medium",
                    "HTML comment written as instructions to an AI",
                    _excerpt(node.text),
                    node.parent.path(),
                    node.line,
                    verdict.score,
                    verdict.reasons,
                )
            )

    def _attributes(self, el: Element) -> None:
        for name in READ_ATTRIBUTES:
            value = el.attrs.get(name)
            if not value:
                continue
            self.findings.extend(_smuggling_findings(value, f"{el.path()} [{name}]", el.line))
            verdict = intent.analyse(value)
            if verdict.is_instruction:
                self.findings.append(
                    Finding(
                        "attribute",
                        "medium",
                        f'{name}="..." attribute written as instructions to an AI',
                        _excerpt(value),
                        f"{el.path()} [{name}]",
                        el.line,
                        verdict.score,
                        verdict.reasons,
                    )
                )

    def _hidden_finding(self, origin: Element, texts: list[Text]) -> None:
        text = collapse(" ".join(t.text for t in texts))
        if not text:
            return
        verdict = intent.analyse(text)
        if verdict.is_instruction:
            severity = "high"
        elif len(text) >= 80:
            severity = "medium"
        else:
            severity = "low"
        self.findings.append(
            Finding(
                "hidden-text",
                severity,
                self.hidden_detail[origin],
                _excerpt(text),
                origin.path(),
                origin.line,
                verdict.score,
                verdict.reasons,
            )
        )


def _smuggling_findings(text: str, location: str, line: int) -> list[Finding]:
    out = []
    for s in smuggling.find(text):
        if s.technique in ("unicode-tags", "variation-selectors"):
            severity, detail = "high", f"{s.count} invisible characters that decode to text"
        elif s.technique == "bidi-controls":
            severity, detail = "medium", f"{s.count} bidirectional control characters (text may read differently)"
        else:
            severity = "medium" if s.count >= 10 else "low"
            detail = f"{s.count} zero-width characters"
        verdict = intent.analyse(s.decoded) if s.decoded else intent.Intent(0.0, ())
        out.append(
            Finding(
                s.technique,
                severity,
                detail,
                _excerpt(s.decoded),
                location,
                line,
                verdict.score,
                verdict.reasons,
            )
        )
    return out


def _excerpt(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
