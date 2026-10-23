"""Minimal HTML tree on top of html.parser. Never fails on broken HTML."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


VOID_TAGS = _words("area base br col embed hr img input link meta param source track wbr")
BLOCK_TAGS = _words(
    "address article aside blockquote br dd div dl dt fieldset figcaption figure footer form "
    "h1 h2 h3 h4 h5 h6 header hr li main nav ol p pre section table tr td th ul"
)
# text inside these is not shown on the page
NON_RENDERED_TAGS = _words("script style template head title noscript")


@dataclass(eq=False)
class Text:
    text: str
    parent: Element
    line: int


@dataclass(eq=False)
class Comment:
    text: str
    parent: Element
    line: int


@dataclass(eq=False)
class Element:
    tag: str
    attrs: dict[str, str]
    parent: Element | None = None
    line: int = 0
    children: list[Element | Text | Comment] = field(default_factory=list)

    @property
    def id(self) -> str | None:
        return self.attrs.get("id")

    @property
    def classes(self) -> frozenset[str]:
        return frozenset(self.attrs.get("class", "").split())

    def ancestors(self) -> Iterator[Element]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def path(self) -> str:
        """e.g. 'body > div.footer > span'"""
        parts = []
        for el in [self, *self.ancestors()]:
            if el.tag in ("#document", "html"):
                break
            label = el.tag
            if el.id:
                label += f"#{el.id}"
            elif el.classes:
                label += "." + ".".join(sorted(el.classes)[:2])
            parts.append(label)
        return " > ".join(reversed(parts)) or self.tag

    def iter(self) -> Iterator[Element | Text | Comment]:
        for child in self.children:
            yield child
            if isinstance(child, Element):
                yield from child.iter()

    def text_content(self) -> str:
        return collapse(_collect_text(self))


def parse(html: str) -> Element:
    builder = _Builder()
    builder.feed(html)
    builder.close()
    return builder.root


def collapse(text: str) -> str:
    """Normalise whitespace inside lines and drop blank lines."""
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _collect_text(el: Element) -> str:
    out = []
    for child in el.children:
        if isinstance(child, Text):
            out.append(child.text)
        elif isinstance(child, Element) and child.tag not in ("script", "style", "template"):
            sep = "\n" if child.tag in BLOCK_TAGS else ""
            out.append(sep + _collect_text(child) + sep)
    return "".join(out)


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#document", {})
        self._stack = [self.root]

    @property
    def _current(self) -> Element:
        return self._stack[-1]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        el = self._make(tag, attrs)
        if tag not in VOID_TAGS:
            self._stack.append(el)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._make(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._current.children.append(Text(data, self._current, self.getpos()[0]))

    def handle_comment(self, data: str) -> None:
        self._current.children.append(Comment(data, self._current, self.getpos()[0]))

    def _make(self, tag: str, attrs: list[tuple[str, str | None]]) -> Element:
        el = Element(
            tag=tag,
            attrs={k.lower(): (v or "") for k, v in attrs},
            parent=self._current,
            line=self.getpos()[0],
        )
        self._current.children.append(el)
        return el
