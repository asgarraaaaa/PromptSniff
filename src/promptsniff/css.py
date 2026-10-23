"""The bit of CSS needed to know if some text is visible.

Supports inline styles, <style> blocks, tag/class/id selectors, compound and
descendant selectors, specificity and !important. Rules with other selectors
are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from promptsniff.dom import Element

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_SIMPLE_PART = re.compile(r"^(?P<tag>[a-zA-Z][\w-]*|\*)?(?P<rest>(?:[.#][\w-]+)*)$")


@dataclass(frozen=True)
class Compound:
    tag: str | None
    id: str | None
    classes: frozenset[str]

    def matches(self, el: Element) -> bool:
        if self.tag is not None and self.tag != el.tag:
            return False
        if self.id is not None and self.id != el.id:
            return False
        return self.classes <= el.classes


@dataclass(frozen=True)
class Rule:
    selector: tuple[Compound, ...]
    specificity: tuple[int, int, int]
    order: int
    declarations: dict[str, tuple[str, bool]]

    def matches(self, el: Element) -> bool:
        *ancestors, last = self.selector
        if not last.matches(el):
            return False
        node = el.parent
        for compound in reversed(ancestors):
            while node is not None and not compound.matches(node):
                node = node.parent
            if node is None:
                return False
            node = node.parent
        return True


def parse_declarations(text: str) -> dict[str, tuple[str, bool]]:
    """'color: red; font-size: 0 !important' -> {property: (value, important)}"""
    out: dict[str, tuple[str, bool]] = {}
    for part in _COMMENT.sub("", text).split(";"):
        if ":" not in part:
            continue
        prop, value = part.split(":", 1)
        value = value.strip()
        important = value.lower().endswith("!important")
        if important:
            value = value[: -len("!important")].strip()
        prop = prop.strip().lower()
        if prop and value:
            out[prop] = (value.lower(), important)
    return out


def parse_stylesheet(css: str, start_order: int = 0) -> list[Rule]:
    # rules inside @media are kept too, they can be used to hide text on screen only
    rules: list[Rule] = []
    _parse_block(_COMMENT.sub("", css), rules, start_order)
    return rules


def _parse_block(css: str, rules: list[Rule], order: int) -> int:
    i = 0
    while i < len(css):
        open_brace = css.find("{", i)
        if open_brace == -1:
            break
        prelude = css[i:open_brace].strip()
        close_brace = _matching_brace(css, open_brace)
        body = css[open_brace + 1 : close_brace]
        if prelude.startswith("@"):
            if "{" in body:
                order = _parse_block(body, rules, order)
        else:
            declarations = parse_declarations(body)
            for selector_text in prelude.split(","):
                selector = _parse_selector(selector_text)
                if selector is not None and declarations:
                    rules.append(Rule(selector, _specificity(selector), order, declarations))
                    order += 1
        i = close_brace + 1
    return order


def _matching_brace(css: str, open_brace: int) -> int:
    depth = 0
    for j in range(open_brace, len(css)):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    return len(css)


def _parse_selector(text: str) -> tuple[Compound, ...] | None:
    compounds = []
    for part in text.split():
        m = _SIMPLE_PART.match(part)
        if m is None:
            return None
        tag = m["tag"] if m["tag"] not in (None, "*") else None
        rest = m["rest"]
        ids = re.findall(r"#([\w-]+)", rest)
        classes = frozenset(re.findall(r"\.([\w-]+)", rest))
        compounds.append(Compound(tag.lower() if tag else None, ids[0] if ids else None, classes))
    return tuple(compounds) or None


def _specificity(selector: tuple[Compound, ...]) -> tuple[int, int, int]:
    ids = sum(c.id is not None for c in selector)
    classes = sum(len(c.classes) for c in selector)
    tags = sum(c.tag is not None for c in selector)
    return ids, classes, tags


def cascade(el: Element, rules: list[Rule]) -> dict[str, str]:
    """The declared (not inherited) values that apply to one element."""
    candidates: list[tuple[tuple, str, str]] = []
    for rule in rules:
        if rule.matches(el):
            for prop, (value, important) in rule.declarations.items():
                candidates.append(((important, False, rule.specificity, rule.order), prop, value))
    for prop, (value, important) in parse_declarations(el.attrs.get("style", "")).items():
        candidates.append(((important, True, (0, 0, 0), 0), prop, value))
    candidates.sort(key=lambda c: c[0])
    return {prop: value for _, prop, value in candidates}


_NAMED_COLOURS = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 128, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "silver": (192, 192, 192),
    "whitesmoke": (245, 245, 245),
    "snow": (255, 250, 250),
    "ivory": (255, 255, 240),
    "beige": (245, 245, 220),
    "navy": (0, 0, 128),
    "orange": (255, 165, 0),
}

RGBA = tuple[float, float, float, float]


def parse_colour(value: str) -> RGBA | None:
    """Parse #rgb, #rrggbb(aa), rgb()/rgba(), a few names and 'transparent'."""
    value = value.strip().lower()
    if value == "transparent":
        return (0, 0, 0, 0.0)
    if value in _NAMED_COLOURS:
        return (*_NAMED_COLOURS[value], 1.0)
    if value.startswith("#"):
        h = value[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        if len(h) in (6, 8) and all(c in "0123456789abcdef" for c in h):
            r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
            a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
            return (r, g, b, a)
        return None
    m = re.fullmatch(r"rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)", value)
    if m:
        alpha = m[4] or "1"
        a = float(alpha[:-1]) / 100 if alpha.endswith("%") else float(alpha)
        return (float(m[1]), float(m[2]), float(m[3]), a)
    return None


def colour_from_background(value: str) -> RGBA | None:
    """Find the colour in a 'background' shorthand, e.g. '#fff url(x.png)'."""
    for token in re.findall(r"rgba?\([^)]*\)|#[0-9a-f]+|[a-z]+", value):
        colour = parse_colour(token)
        if colour is not None:
            return colour
    return None


def parse_length(value: str, parent_px: float, root_px: float = 16.0) -> float | None:
    """CSS length to pixels, None if not understood."""
    m = re.fullmatch(r"(-?[\d.]+)(px|pt|em|rem|%|vw|vh)?", value.strip())
    if m is None:
        named = {"xx-small": 9, "x-small": 10, "small": 13, "medium": 16, "large": 18, "x-large": 24}
        return float(named[value]) if value in named else None
    number, unit = float(m[1]), m[2]
    if unit in (None, "px"):
        return number
    if unit == "pt":
        return number * 4 / 3
    if unit == "em":
        return number * parent_px
    if unit == "rem":
        return number * root_px
    if unit == "%":
        return number / 100 * parent_px
    return number * 10  # vw/vh: assume a ~1000px viewport


def blend(top: RGBA, bottom: tuple[float, float, float]) -> tuple[float, float, float]:
    a = top[3]
    return tuple(top[i] * a + bottom[i] * (1 - a) for i in range(3))  # type: ignore[return-value]


def contrast_ratio(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """WCAG 2 contrast ratio, from 1 (identical) to 21 (black on white)."""

    def luminance(c: tuple[float, float, float]) -> float:
        def channel(v: float) -> float:
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

        r, g, b_ = (channel(x) for x in c)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b_

    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)
