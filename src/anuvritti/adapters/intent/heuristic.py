"""Deterministic, offline Intent Engine (ADR-0004).

PRD 13 makes intent understanding the core AI capability, but PRD 8.1 puts the human
first and PRD 49 rules out advanced agents in V0. So this adapter is rules and lexicons:
it never leaves the device, it always gives the same answer twice, and it never claims to
be certain - certainty is reserved for what a person actually said (PRD 8.7).

Swapping in an LLM means writing one new class behind `IntentEngine`. Nothing else moves.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Final
from urllib.parse import urlparse

from anuvritti.domain.spark import UNCATEGORISED, Inference
from anuvritti.domain.values import (
    MAX_CHILD_AGE,
    AgeRange,
    Confidence,
    IntentType,
    SourceRef,
)

_MAX_TAGS: Final = 6
_MAX_CONFIDENCE: Final = 0.85  # never CERTAIN - that belongs to the human (PRD 8.7)

#: Words that suggest an intent. Weighted: an explicit verb beats an incidental noun.
_INTENT_LEXICON: Final[Mapping[IntentType, Mapping[str, float]]] = {
    IntentType.BUY: {
        "buy": 3.0,
        "purchase": 3.0,
        "order": 2.0,
        "price": 2.5,
        "wishlist": 3.0,
        "gift": 2.0,
        "shop": 2.0,
        "sale": 1.5,
        "discount": 1.5,
        "cart": 2.0,
    },
    IntentType.WATCH: {
        "watch": 3.0,
        "movie": 2.5,
        "film": 2.5,
        "episode": 2.0,
        "series": 2.0,
        "trailer": 2.0,
        "documentary": 2.5,
        "animated": 2.0,
        "cartoon": 2.0,
    },
    IntentType.READ: {
        "read": 3.0,
        "book": 2.5,
        "story": 1.5,
        "novel": 2.5,
        "chapter": 2.0,
        "author": 2.0,
        "poem": 2.0,
        "comic": 2.0,
    },
    IntentType.TEACH: {
        "teach": 3.5,
        "lesson": 3.0,
        "explain": 2.5,
        "learn": 1.5,
        "values": 2.0,
        "manners": 2.5,
        "honesty": 2.0,
        "patience": 2.0,
        "kindness": 2.0,
        "apolog": 2.0,
        "sorry": 1.5,
        "skill": 2.0,
    },
    IntentType.DO: {
        "experiment": 3.0,
        "activity": 3.0,
        "craft": 3.0,
        "make": 2.0,
        "build": 2.0,
        "diy": 3.0,
        "play": 2.0,
        "together": 2.0,
        "try": 1.5,
        "recipe": 2.5,
        "cook": 2.5,
        "bake": 2.5,
        "visit": 2.0,
        "trip": 2.0,
        "museum": 2.0,
        "project": 2.0,
        "game": 2.0,
    },
}

#: Hosts are weaker evidence than words, but better than nothing for a bare link.
_HOST_LEXICON: Final[Mapping[str, tuple[IntentType, float]]] = {
    "youtube.com": (IntentType.WATCH, 2.0),
    "youtu.be": (IntentType.WATCH, 2.0),
    "netflix.com": (IntentType.WATCH, 2.5),
    "primevideo.com": (IntentType.WATCH, 2.5),
    "amazon.com": (IntentType.BUY, 2.0),
    "amazon.in": (IntentType.BUY, 2.0),
    "etsy.com": (IntentType.BUY, 2.5),
    "flipkart.com": (IntentType.BUY, 2.0),
    "goodreads.com": (IntentType.READ, 2.5),
    "gutenberg.org": (IntentType.READ, 2.5),
    "allrecipes.com": (IntentType.DO, 2.0),
}

_CATEGORY_LEXICON: Final[Mapping[str, tuple[str, ...]]] = {
    "toy": ("toy", "bike", "lego", "blocks", "puzzle", "train set", "doll", "plush"),
    "science-activity": ("experiment", "science", "volcano", "rocket", "chemistry", "physics"),
    "food": ("recipe", "cook", "bake", "meal", "snack", "dal", "breakfast", "lunch", "dinner"),
    "book": ("book", "story", "novel", "poem", "comic", "chapter", "author"),
    "film": ("movie", "film", "cartoon", "animated", "documentary", "episode", "series"),
    "place": ("museum", "park", "zoo", "trip", "visit", "beach", "aquarium", "garden"),
    "craft": ("craft", "origami", "paint", "draw", "diy", "paper"),
    "music": ("song", "music", "lullaby", "sing", "guitar", "piano"),
    "life-skill": (
        "teach",
        "lesson",
        "manners",
        "honesty",
        "patience",
        "kindness",
        "apolog",
        "responsib",
        "sharing",
        "skill",
    ),
    "outdoor": ("outdoor", "hike", "camping", "cycling", "playground", "garden"),
}

#: Named developmental stages. Deliberately broad - these are hints, not assessments.
_STAGE_AGES: Final[Mapping[str, tuple[int, int]]] = {
    "newborn": (0, 1),
    "infant": (0, 1),
    "toddler": (1, 3),
    "preschool": (3, 5),
    "kindergarten": (4, 6),
    "primary school": (6, 10),
    "tween": (10, 12),
    "teen": (13, 17),
}

# en dash and hyphen both appear in real captions, so both are accepted here
_RANGE_RE: Final = re.compile("\\b(?:age[sd]?\\s*)?(\\d{1,2})\\s*(?:-|to|\u2013)\\s*(\\d{1,2})\\b")
_SINGLE_RE: Final = re.compile(r"\b(\d{1,2})\s*(?:\+|year[- ]?olds?|yo)\b")
_WORD_RE: Final = re.compile(r"[a-z]+")


class HeuristicIntentEngine:
    """Rule-based inference. Same input, same answer, no network, no surprises."""

    def infer(self, source: SourceRef, *, note: str | None = None) -> Inference:
        corpus = self._corpus(source, note)
        # What the parent typed is the strongest evidence available (PRD 8.1).
        weighted = self._score_intents(corpus, note)
        intent, strength = self._best_intent(weighted, source)
        category, category_strength = self._categorise(corpus)
        age_range = self._age_range(corpus)

        return Inference(
            title=source.display_title() or source.kind.value.title(),
            intent=intent,
            intent_confidence=self._confidence(strength),
            category=category,
            category_confidence=self._confidence(category_strength),
            age_range=age_range,
            age_confidence=Confidence(0.6) if age_range else None,
            tags=self._tags(corpus),
        )

    # ------------------------------------------------------------------ text
    def _corpus(self, source: SourceRef, note: str | None) -> str:
        parts: list[str] = [source.title or "", source.text or "", source.creator or "", note or ""]
        if source.url:
            parsed = urlparse(source.url)
            parts.append(parsed.path.replace("/", " ").replace("-", " "))
        return " ".join(parts).lower()

    # ---------------------------------------------------------------- intent
    def _score_intents(self, corpus: str, note: str | None) -> dict[IntentType, float]:
        scores: dict[IntentType, float] = dict.fromkeys(_INTENT_LEXICON, 0.0)
        note_text = (note or "").lower()
        for intent, lexicon in _INTENT_LEXICON.items():
            for term, weight in lexicon.items():
                if term in corpus:
                    scores[intent] += weight
                    # The parent's own words count double. They were there; we were not.
                    if term in note_text:
                        scores[intent] += weight
        return scores

    def _best_intent(
        self, scores: dict[IntentType, float], source: SourceRef
    ) -> tuple[IntentType, float]:
        if source.url:
            host = urlparse(source.url).netloc.removeprefix("www.")
            if host in _HOST_LEXICON:
                intent, weight = _HOST_LEXICON[host]
                scores[intent] += weight

        intent, strength = max(scores.items(), key=lambda item: (item[1], item[0].value))
        if strength <= 0.0:
            # "I want to remember this" is the honest answer when nothing else is clear.
            return IntentType.REMEMBER, 0.0
        return intent, strength

    # -------------------------------------------------------------- category
    def _categorise(self, corpus: str) -> tuple[str, float]:
        best, best_hits = UNCATEGORISED, 0
        for category, terms in _CATEGORY_LEXICON.items():
            hits = sum(1 for term in terms if term in corpus)
            if hits > best_hits:
                best, best_hits = category, hits
        return best, float(best_hits) * 2.0

    def _tags(self, corpus: str) -> tuple[str, ...]:
        found: list[str] = [
            category
            for category, terms in _CATEGORY_LEXICON.items()
            if any(term in corpus for term in terms)
        ]
        return tuple(dict.fromkeys(found))[:_MAX_TAGS]

    # ------------------------------------------------------------------- age
    def _age_range(self, corpus: str) -> AgeRange | None:
        """Read an age only when the text states one. A guess here distorts every
        future suggestion, so silence is the safer answer."""
        match = _RANGE_RE.search(corpus)
        if match:
            low, high = sorted((int(match.group(1)), int(match.group(2))))
            return self._safe_range(low, high)

        single = _SINGLE_RE.search(corpus)
        if single:
            age = int(single.group(1))
            return self._safe_range(age, age)

        for stage, (low, high) in _STAGE_AGES.items():
            if stage in corpus:
                return self._safe_range(low, high)
        return None

    def _safe_range(self, low: int, high: int) -> AgeRange | None:
        if low < 0 or high > MAX_CHILD_AGE:
            return None
        try:
            return AgeRange(low, high)
        except ValueError:  # pragma: no cover - defensive; _safe_range pre-checks
            return None

    # ------------------------------------------------------------ confidence
    def _confidence(self, strength: float) -> Confidence:
        """Map evidence to a calibrated probability, capped below certainty.

        The cap is the point: an inference is a suggestion the human can overrule, and
        the interface shows low confidence as a question rather than a fact.
        """
        if strength <= 0.0:
            return Confidence(0.2)
        return Confidence(min(_MAX_CONFIDENCE, 0.35 + strength * 0.08))


def available_categories() -> Iterable[str]:
    return _CATEGORY_LEXICON.keys()
