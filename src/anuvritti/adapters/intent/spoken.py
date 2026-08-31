"""The Intent Engine, taught to listen (TASK-604; PRD 13, 48).

PRD 13's list of intents is not a taxonomy. Read it again and it is eight sentences a
parent says out loud:

    "I want to buy this."   "I want to do this with him."   "I want him to watch this
    someday."   "I want to teach him this."   "This reminds me of my childhood."

`HeuristicIntentEngine` never sees sentences like that, because it was built for captions
and page titles - nouns, hashtags and product names, where "buy" appears as a button label
rather than as something a person wants. Speech is the opposite: the verb is the whole
signal, it is in the first person, and it is usually the only signal there is, because a
transcript has no host, no title and no URL.

So a transcript run through the caption engine alone gets *less* understanding than a typed
note would, which would make speaking the expensive way to save something. TASK-604 exists
to close exactly that gap, and `tests/unit/adapters/test_heuristic_voice.py` asserts parity
in the strong direction: the same words spoken must never be understood worse than the same
words typed.

Three things about speech that captions never do, and that this layer handles:

**People correct themselves.** "I want to watch- no, I want to *do* this with him." The
last statement wins, so matches are weighted by where they fall. A caption has no order to
speak of; a sentence does.

**People negate.** "I don't want to buy him another one of these." The caption engine sees
`buy` and scores BUY, which is the exact opposite of what was said. Negation is scoped to
the clause, because "I don't want to buy it, I want to make it with him" contains both a
suppressed intent and a real one.

**People say nothing, at length.** "Um, so, like, this is the thing I was, you know,
talking about." Fillers are removed before anything is scored, so a hesitant parent is not
read as a less certain one.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Final

from anuvritti.application.ports import IntentEngine
from anuvritti.domain.lexicon import FamilyLexicon
from anuvritti.domain.spark import Inference
from anuvritti.domain.values import Confidence, IntentType, SourceKind, SourceRef

#: Never certainty. A parent saying "I want to buy this" is strong evidence about what they
#: meant, and still an inference about a sentence a machine transcribed (PRD 8.7).
MAX_CONFIDENCE: Final = 0.85

#: Where a vetoed reading lands. Deliberately low: knowing what someone did *not* mean is
#: not the same as knowing what they did.
VETOED_CONFIDENCE: Final = Confidence(0.3)

#: Genuine disfluencies, removed before scoring. Deliberately short.
#:
#: "like", "sort of" and "basically" are *not* here, and "actually" is emphatically not:
#: it is a clause boundary below, and a parent saying "actually, let's build it" is marking
#: the exact point where they changed their mind. Deleting the word that carries the
#: correction would leave the layer reading the sentence they abandoned.
FILLERS: Final[tuple[str, ...]] = ("um", "uh", "erm", "hmm", "mmm", "you know", "i mean")

#: Phrases people actually say, mapped to what they meant. Ordered longest-first at match
#: time, so "want to show him" does not also fire the weaker "show him".
_SPOKEN: Final[Mapping[IntentType, tuple[tuple[str, float], ...]]] = {
    IntentType.BUY: (
        ("want to buy", 4.0),
        ("should buy", 3.5),
        ("we should get him", 3.5),
        ("we should get her", 3.5),
        ("get him one", 3.5),
        ("get her one", 3.5),
        ("buy him", 3.5),
        ("buy her", 3.5),
        ("for his birthday", 2.5),
        ("for her birthday", 2.5),
        ("add to the list", 2.0),
    ),
    IntentType.DO: (
        ("want to do this with", 4.5),
        ("do this with him", 4.0),
        ("do this with her", 4.0),
        ("we should try", 3.5),
        ("we should make", 3.5),
        ("let us make", 3.5),
        ("lets make", 3.5),
        ("let us try", 3.5),
        ("lets try", 3.5),
        ("lets do", 3.5),
        ("let us do", 3.5),
        ("this weekend", 2.5),
        ("take him", 2.5),
        ("take her", 2.5),
        ("build this", 3.0),
    ),
    IntentType.WATCH: (
        ("want him to watch", 4.5),
        ("want her to watch", 4.5),
        ("show him this", 4.0),
        ("show her this", 4.0),
        ("watch this together", 4.0),
        ("when he is older", 2.0),
        ("when she is older", 2.0),
    ),
    IntentType.READ: (
        ("read this to him", 4.5),
        ("read this to her", 4.5),
        ("read him", 3.5),
        ("read her", 3.5),
        ("at bedtime", 2.5),
        ("bedtime story", 3.0),
    ),
    IntentType.TEACH: (
        ("want to teach him", 4.5),
        ("want to teach her", 4.5),
        ("teach him", 4.0),
        ("teach her", 4.0),
        ("he should learn", 3.5),
        ("she should learn", 3.5),
        ("wanted him to know", 3.5),
        ("wanted her to know", 3.5),
        ("want him to know", 3.5),
        ("want her to know", 3.5),
    ),
    IntentType.REMEMBER: (
        ("want to remember", 4.0),
        ("do not want to forget", 4.0),
        ("dont want to forget", 4.0),
        ("note to self", 3.5),
        ("reminds me of my childhood", 4.0),
        ("reminds me of when i was", 4.0),
        ("thought you would have laughed", 3.5),
        ("he said", 2.0),
        ("she said", 2.0),
        ("he called", 2.0),
        ("she called", 2.0),
    ),
    IntentType.COOK: (
        ("want to cook this with", 4.5),
        ("want to cook with him", 4.5),
        ("want to cook with her", 4.5),
        ("want to bake with him", 4.5),
        ("want to bake with her", 4.5),
        ("want to cook", 4.0),
        ("want to bake", 4.0),
        ("we should bake", 4.0),
        ("we should cook", 4.0),
        ("make this recipe", 4.0),
        ("cook this with", 4.0),
        ("bake this with", 4.0),
        ("cook together", 3.5),
        ("bake together", 3.5),
        ("recipe for", 3.0),
    ),
    IntentType.VISIT: (
        ("want to visit", 4.5),
        ("we should visit", 4.0),
        ("want to take him to", 4.5),
        ("want to take her to", 4.5),
        ("take him to the", 4.5),
        ("take her to the", 4.5),
        ("take him to", 4.0),
        ("take her to", 4.0),
        ("go to the", 3.5),
        ("trip to", 3.5),
        ("visit the", 3.5),
        ("travel to", 3.5),
        ("go visit", 3.5),
    ),
    IntentType.TELL: (
        ("want to tell him", 4.5),
        ("want to tell her", 4.5),
        ("tell him about", 4.0),
        ("tell her about", 4.0),
        ("tell him the story", 4.0),
        ("tell her the story", 4.0),
        ("tell a story", 3.5),
        ("story to tell", 3.5),
    ),
    IntentType.LISTEN: (
        ("want him to listen to", 4.5),
        ("want her to listen to", 4.5),
        ("want him to hear", 4.5),
        ("want her to hear", 4.5),
        ("listen to this with", 4.0),
        ("listen to this song", 4.0),
        ("we should listen to", 3.5),
        ("play this song for", 3.5),
        ("listen together", 3.5),
    ),
}

#: Negation inside a clause suppresses every intent scored in that clause. "I don't want to
#: buy him another one" is evidence *against* BUY, and reading it as evidence for BUY is
#: worse than reading nothing at all.
#:
#: Written without apostrophes because `_spoken_corpus` flattens them first - iOS and
#: Android transcribe the same contraction three different ways between them, and matching
#: "don't" would silently miss two of the three.
_NEGATORS: Final[tuple[str, ...]] = (
    "not",
    "dont",
    "doesnt",
    "didnt",
    "wont",
    "cant",
    "never",
)

#: Where one thought ends and the next begins. Transcripts rarely have punctuation, so the
#: coordinators do most of the work.
_CLAUSE_SPLIT: Final = re.compile(r"[.!?;,]|\bbut\b|\bthough\b|\bactually\b|\binstead\b|\bno\b")

_APOSTROPHE: Final = re.compile("[\u2019']")
_NEGATED: Final = re.compile(r"\b(?:" + "|".join(_NEGATORS) + r")\b")
_FILLER_RE: Final = re.compile(
    r"\b(?:" + "|".join(f.replace(" ", r"\s+") for f in FILLERS) + r")\b"
)


class SpokenIntentEngine:
    """Wraps a text engine and adds the way people actually talk.

    A decorator rather than a replacement, and it delegates untouched for anything that is
    not a recording. Captions, page titles and typed notes still go through the engine that
    was built for them; nothing about the existing behaviour moves.
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: IntentEngine) -> None:
        self._inner = inner

    def infer(
        self,
        source: SourceRef,
        *,
        note: str | None = None,
        lexicon: FamilyLexicon | None = None,
    ) -> Inference:
        if source.kind is not SourceKind.VOICE:
            return self._inner.infer(source, note=note, lexicon=lexicon)

        # A transcript *is* the parent's own words, so it is handed to the inner engine as
        # the note. That engine already weights a note double - "They were there; we were
        # not" - and a transcript has a better claim to that than a typed caption does.
        # Without this line, speaking would earn strictly less understanding than typing
        # the same sentence, which is the exact gap TASK-604 exists to close.
        base = self._inner.infer(source, note=note or source.text, lexicon=lexicon)

        spoken = _spoken_corpus(source, note)
        if not spoken:
            return base

        heard, strength, vetoed = _what_was_said(spoken)
        if heard is None:
            if base.intent in vetoed:
                # The parent said the opposite of what the words look like. Refusing to add
                # evidence is not enough here: the caption engine has already scored `buy`
                # off "I don't want to buy him another one", and letting that stand would
                # file the Spark under the one thing the parent ruled out.
                #
                # The replacement is REMEMBER at low confidence, because knowing what
                # someone did *not* mean is not the same as knowing what they did.
                return replace(
                    base, intent=IntentType.REMEMBER, intent_confidence=VETOED_CONFIDENCE
                )
            # Nothing recognisable was said about what to do with it. The caption engine's
            # answer stands, which for a bare transcript is usually REMEMBER - and "I want
            # to remember this" is the honest reading of someone recording their own voice.
            return base

        spoken_confidence = _confidence(strength)
        if base.intent is heard and base.intent_confidence >= spoken_confidence:
            # The two agree and the text engine was already surer. Leave it alone: parity
            # means voice is never understood *worse*, not that it always overrides.
            return base

        return Inference(
            title=base.title,
            intent=heard,
            intent_confidence=spoken_confidence,
            category=base.category,
            category_confidence=base.category_confidence,
            age_range=base.age_range,
            age_confidence=base.age_confidence,
            tags=base.tags,
        )


def _spoken_corpus(source: SourceRef, note: str | None) -> str:
    """The transcript and whatever the parent typed alongside it, cleaned of fillers.

    Apostrophes are flattened rather than stripped so that "don't" becomes "dont" and stays
    a single token, which is what the negation list is written against - iOS and Android
    transcribe the same contraction three different ways between them.
    """
    said = " ".join(part for part in (source.text, note) if part).lower()
    said = _APOSTROPHE.sub("", said)
    return " ".join(_FILLER_RE.sub(" ", said).split())


def _what_was_said(spoken: str) -> tuple[IntentType | None, float, frozenset[IntentType]]:
    """Score each clause, and separate what was said from what was ruled out.

    Returns the best intent, its strength, and the set of intents that were *vetoed* -
    named inside a negated clause and never affirmed anywhere else. The veto is the half
    that is easy to leave out, and leaving it out is how "I don't want to buy him another
    one" ends up filed under BUY.

    The recency weighting is the other thing a caption has no notion of. In a caption every
    word is equally present. In a sentence, "I was going to buy it, but actually let's build
    it together" has two intents in it and only one of them is what the parent decided.
    """
    clauses = [clause.strip() for clause in _CLAUSE_SPLIT.split(spoken) if clause.strip()]
    if not clauses:
        return None, 0.0, frozenset()

    scores: dict[IntentType, float] = {}
    refused: set[IntentType] = set()
    for position, clause in enumerate(clauses):
        negated = _is_negated(clause)
        # 1.0 for the first clause rising to 1.5 for the last: later is a correction of
        # earlier, not a second opinion of equal weight.
        recency = 1.0 + 0.5 * (position / max(1, len(clauses) - 1))
        for intent, phrases in _SPOKEN.items():
            for phrase, weight in phrases:
                if phrase not in clause:
                    continue
                # A phrase that carries its own negation is immune to the clause's.
                # "I don't want to forget this" is not a suppressed REMEMBER - it is the
                # single most emphatic way a parent ever says REMEMBER, and reading the
                # "don't" as a suppressor would drop the one they meant most.
                if negated and _NEGATED.search(phrase) is None:
                    refused.add(intent)
                    break
                scores[intent] = scores.get(intent, 0.0) + weight * recency
                break  # longest-first within an intent; one phrase is one statement

    vetoed = frozenset(refused - set(scores))
    if not scores:
        return None, 0.0, vetoed
    best = max(scores.items(), key=lambda item: (item[1], item[0].value))
    return best[0], best[1], vetoed


def _is_negated(clause: str) -> bool:
    return _NEGATED.search(clause) is not None


def _confidence(strength: float) -> Confidence:
    """Spoken evidence is strong evidence, and still capped below certainty.

    The floor is higher than the caption engine's because a first-person verb is a better
    signal than a keyword on a page: someone saying "I want to teach him this" has told you
    what they meant, where a page containing the word "teach" merely might have.
    """
    return Confidence(min(MAX_CONFIDENCE, 0.45 + strength * 0.07))


def spoken_phrases() -> Sequence[str]:
    """Every phrase this layer listens for. Used by the parity tests, and by nothing else."""
    return [phrase for phrases in _SPOKEN.values() for phrase, _ in phrases]
