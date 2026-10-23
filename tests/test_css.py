import pytest

from promptsniff.css import cascade, contrast_ratio, parse_colour, parse_declarations, parse_length, parse_stylesheet
from promptsniff.dom import Element, parse


def find(root: Element, tag: str) -> Element:
    return next(n for n in root.iter() if isinstance(n, Element) and n.tag == tag)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("#fff", (255, 255, 255, 1.0)),
        ("#000000", (0, 0, 0, 1.0)),
        ("#ff000080", (255, 0, 0, 128 / 255)),
        ("rgb(10, 20, 30)", (10, 20, 30, 1.0)),
        ("rgba(10,20,30,0.5)", (10, 20, 30, 0.5)),
        ("rgb(10 20 30 / 50%)", (10, 20, 30, 0.5)),
        ("White", (255, 255, 255, 1.0)),
        ("transparent", (0, 0, 0, 0.0)),
    ],
)
def test_parse_colour(value, expected):
    assert parse_colour(value) == pytest.approx(expected)


@pytest.mark.parametrize("value", ["#ggg", "hsl(0, 0%, 0%)", "currentColor", ""])
def test_parse_colour_unknown(value):
    assert parse_colour(value) is None


@pytest.mark.parametrize(
    "value, parent, expected",
    [("0", 16, 0), ("12px", 16, 12), ("12pt", 16, 16), ("0.5em", 20, 10), ("2rem", 99, 32), ("50%", 20, 10)],
)
def test_parse_length(value, parent, expected):
    assert parse_length(value, parent) == pytest.approx(expected)


def test_contrast_ratio_extremes():
    assert contrast_ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21, abs=0.01)
    assert contrast_ratio((200, 10, 10), (200, 10, 10)) == pytest.approx(1)


def test_declarations_handle_important_and_comments():
    d = parse_declarations("color: Red; /* hi */ font-size: 0 !important;;broken")
    assert d == {"color": ("red", False), "font-size": ("0", True)}


def test_specificity_inline_and_important():
    css = """
      p { color: red; }
      .note { color: blue; }
      #x { color: green; }
      p { font-size: 1px !important; }
    """
    root = parse('<p id="x" class="note" style="color: black; font-size: 20px">hi</p>')
    styles = cascade(find(root, "p"), parse_stylesheet(css))
    assert styles["color"] == "black"  # inline beats any selector
    assert styles["font-size"] == "1px"  # !important beats inline


def test_descendant_selectors_and_lists():
    rules = parse_stylesheet("footer .legal, aside { display: none }")
    root = parse('<footer><div><span class="legal">a</span></div></footer><span class="legal">b</span><aside>c</aside>')
    spans = [n for n in root.iter() if isinstance(n, Element) and n.tag == "span"]
    assert cascade(spans[0], rules) == {"display": "none"}
    assert cascade(spans[1], rules) == {}
    assert cascade(find(root, "aside"), rules) == {"display": "none"}


def test_rules_inside_media_queries_are_kept():
    rules = parse_stylesheet("@media screen and (min-width: 1px) { .x { opacity: 0 } } .y { color: red }")
    assert [r.declarations for r in rules] == [{"opacity": ("0", False)}, {"color": ("red", False)}]


def test_unsupported_selectors_are_skipped_not_guessed():
    rules = parse_stylesheet(
        "div > p { display:none } a:hover { color:red } [hidden] { display:none } p { color: blue }"
    )
    assert len(rules) == 1
