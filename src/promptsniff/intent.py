"""Checks if a piece of text looks like instructions for an AI.

Just regexes (English and Italian), so every result can be explained.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_RULES: list[tuple[str, float, str]] = [
    (
        r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(previous|prior|above|earlier|all|any|your|the)\b"
        r".{0,30}\b(instructions?|prompts?|rules|guidelines|directions)\b",
        0.9,
        "tells the model to drop its instructions",
    ),
    (
        r"\b(ignora|dimentica|trascura)\b.{0,40}\b(istruzioni|regole|indicazioni)\b",
        0.9,
        "tells the model to drop its instructions",
    ),
    (
        r"\b(you are now|from now on,? you|act as|pretend (to be|you are)|your new (task|role|instructions?))\b",
        0.6,
        "assigns the model a new role",
    ),
    (
        r"(\bora sei\b|\bd'ora in poi\b|\bfingi di essere\b|\bcomportati come\b|\bil tuo nuovo (compito|ruolo)\b)",
        0.6,
        "assigns the model a new role",
    ),
    (
        r"\b(ai|llms?|language models?|assistants?|chatbots?|agents?|gpt|claude|gemini|copilot)\b.{0,60}"
        r"\b(must|should|need to|are required to|reading this|reads this|summari[sz]ing)\b",
        0.6,
        "addresses AI systems directly",
    ),
    (
        r"\b(assistente|modello|intelligenza artificiale|ia)\b.{0,60}\b(deve|devi|dovrebbe|sta leggendo)\b",
        0.6,
        "addresses AI systems directly",
    ),
    (
        r"\b(do not|don't|never)\b.{0,20}\b(tell|mention|reveal|inform|disclose|show)\b.{0,30}"
        r"\b(user|human|reader)\b",
        0.7,
        "asks the model to hide something from the user",
    ),
    (
        r"\bnon\b.{0,10}\b(dire|rivelare|menzionare|mostrare)\b.{0,30}\b(utente|lettore)\b",
        0.7,
        "asks the model to hide something from the user",
    ),
    (
        r"(<\|?(im_start|im_end|system|endoftext)\|?>|\[/?inst\]|^\s*(system|assistant)\s*:|\bsystem prompt\b)",
        0.6,
        "imitates chat-template or system-prompt syntax",
    ),
    (
        r"!\[[^\]]*\]\(https?://[^)\s]*[?&][^)\s]*=",
        0.6,
        "builds a markdown image URL with parameters (data exfiltration)",
    ),
    (
        r"\b(send|forward|post|upload|email|leak)\b.{0,40}\b(passwords?|api keys?|tokens?|credentials|cookies?"
        r"|conversation|chat history|secrets?)\b",
        0.8,
        "asks for secrets or conversation data to be sent somewhere",
    ),
    (
        r"\b(recommend|rate|rank|score|hire|approve|praise)\b.{0,40}"
        r"\b(highly|best|top|10/10|five stars|5 stars|strongly|immediately|above all)\b",
        0.4,
        "tries to steer a judgement or recommendation",
    ),
    (
        r"\b(important|attention|note to (the )?(ai|assistant|model|llm))\s*[:!]",
        0.3,
        "uses an attention-grabbing preamble",
    ),
]

_COMPILED = [(re.compile(p, re.I | re.M | re.S), w, why) for p, w, why in _RULES]
THRESHOLD = 0.5


@dataclass(frozen=True)
class Intent:
    score: float
    reasons: tuple[str, ...]

    @property
    def is_instruction(self) -> bool:
        return self.score >= THRESHOLD


def analyse(text: str) -> Intent:
    # each match is treated as independent evidence: 1 - prod(1 - weight)
    remaining = 1.0
    reasons: list[str] = []
    for pattern, weight, why in _COMPILED:
        if pattern.search(text):
            remaining *= 1 - weight
            if why not in reasons:
                reasons.append(why)
    return Intent(score=round(1 - remaining, 3), reasons=tuple(reasons))
