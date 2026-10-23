"""Invisible unicode characters that models read but people don't see.

- tag characters (U+E0000-E007F) map 1:1 to ASCII and render as nothing
- variation selectors can hide one byte each after an emoji
- bidi controls change the display order of text (Trojan Source)
- zero-width characters can split words so filters don't match them
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TAGS = re.compile("[\U000e0000-\U000e007f]+")
_VARIATION = re.compile("[︀-️\U000e0100-\U000e01ef]{2,}")
_BIDI = re.compile("[‪-‮⁦-⁩]")
# no ZWJ/ZWNJ: emojis and some languages (Persian, Hindi) use them normally
_ZERO_WIDTH = re.compile("[​⁠᠎]|(?<!^)﻿")


@dataclass(frozen=True)
class Smuggled:
    technique: str
    count: int
    decoded: str


def find(text: str) -> list[Smuggled]:
    found = []

    tag_runs = _TAGS.findall(text)
    if tag_runs:
        decoded = " ".join(_decode_tags(run) for run in tag_runs)
        found.append(Smuggled("unicode-tags", sum(map(len, tag_runs)), decoded))

    vs_runs = _VARIATION.findall(text)
    if vs_runs:
        decoded = " ".join(_decode_variation_selectors(run) for run in vs_runs)
        found.append(Smuggled("variation-selectors", sum(map(len, vs_runs)), decoded))

    bidi = _BIDI.findall(text)
    if bidi:
        found.append(Smuggled("bidi-controls", len(bidi), ""))

    zero_width = _ZERO_WIDTH.findall(text)
    if zero_width:
        found.append(Smuggled("zero-width", len(zero_width), ""))
    return found


def strip(text: str) -> str:
    for pattern in (_TAGS, _BIDI, _ZERO_WIDTH):
        text = pattern.sub("", text)
    return re.sub("[︀-️\U000e0100-\U000e01ef]", "", text)


def encode_tags(message: str) -> str:
    """Hides ASCII text as tag characters (used for tests and examples)."""
    return "".join(chr(0xE0000 + ord(c)) for c in message if ord(c) < 0x80)


def _decode_tags(run: str) -> str:
    chars = (ord(c) - 0xE0000 for c in run)
    return "".join(chr(c) for c in chars if 0x20 <= c < 0x7F)


def _decode_variation_selectors(run: str) -> str:
    data = bytearray()
    for c in run:
        cp = ord(c)
        data.append(cp - 0xFE00 if cp <= 0xFE0F else cp - 0xE0100 + 16)
    return data.decode("utf-8", errors="replace")
