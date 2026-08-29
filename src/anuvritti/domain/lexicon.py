"""The family's own lexicon (TASK-801; PRD 44, 13, 8.1).

The Intent Engine guesses in general English. A family does not speak general English. In
one house "run" means the park and in another it means a tap that will not stop; "story"
is a book to one family and a thing Nani does at bedtime to another. Every time a parent
taps the intent chip and changes the machine's answer, they have said something true about
their own words, and until now the product forgot it immediately.

This is where it is remembered. Five refusals hold it to PRD 44, and each of them is a
structure rather than a promise:

**A lexicon belongs to one family and there is no way to combine two.** `learn` refuses a
correction that came from a different family, and this module contains no merge, union or
`from_many` — deliberately, and `tests/unit/domain/test_lexicon.py` reads the source to
check that none has appeared. "No public-model training by default" is not a setting here;
there is nowhere to put the other family's data.

**Only a person teaches it.** A `Correction` is constructed from a human override and
nothing else. An engine that learns from its own guesses drifts and calls it learning, and
after a year of that a family's lexicon describes the machine rather than the family.

**One correction is a fact about one Spark; it takes more than one to be a habit.** A term
carries no weight until it has been corrected the same way `MIN_EVIDENCE_TO_SPEAK` times.
The alternative is a product that reorganises itself around a single tap.

**A word the family uses both ways stays silent.** If "story" has been corrected to READ
and to TELL, it teaches nothing, because the honest answer is that this family means both
and the Spark in front of us does not say which. Ambiguity resolves to silence, never to
whichever count happens to be higher this month.

**It holds counts, and cannot reconstruct anything.** There is no Spark id, no child, no
member, no title and no date beyond when a term was last seen in this module. A lexicon
that leaked would say that a family says "sanskaar" and means TEACH. That is the whole of
what it knows.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import FamilyId
from anuvritti.shared.result import Err, Ok, Result

#: Below this a "word" is punctuation or an article, and above the cap a lexicon has
#: stopped being this family's vocabulary and started being a copy of their archive.
MIN_TERM_LENGTH: Final[int] = 3
MAX_TERM_LENGTH: Final[int] = 32
MAX_TERMS: Final[int] = 512

#: How many times a family must say the same thing before the product acts on it.
MIN_EVIDENCE_TO_SPEAK: Final[int] = 2

#: The most a family's own usage may weigh. Deliberately in the same units as the engine's
#: lexicon weights (`adapters/intent/heuristic.py`), and deliberately smaller than the
#: strongest of them: what a family calls a thing is evidence, not a verdict.
MAX_WEIGHT: Final[float] = 2.5

#: Words that carry no meaning about intent in any family. Learning these would make every
#: term in every Spark evidence for whatever the last correction happened to be.
STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "and",
        "the",
        "for",
        "with",
        "this",
        "that",
        "from",
        "you",
        "your",
        "our",
        "his",
        "her",
        "him",
        "she",
        "they",
        "them",
        "was",
        "were",
        "are",
        "have",
        "has",
        "had",
        "not",
        "but",
        "all",
        "any",
        "can",
        "get",
        "got",
        "how",
        "its",
        "one",
        "out",
        "see",
        "too",
        "use",
        "way",
        "who",
        "will",
        "just",
        "like",
        "make",
        "more",
        "some",
        "than",
        "then",
        "very",
        "what",
        "when",
        "where",
        "which",
        "would",
        "about",
        "there",
        "these",
        "those",
        "into",
        "over",
        "http",
        "https",
        "www",
        "com",
    }
)

_WORD_RE: Final = re.compile(r"[a-z][a-z'-]*")


class LexiconField(StrEnum):
    """What a correction was about.

    Only the two fields whose value is a word a family chooses. `age_range` is a number and
    a family does not have private numbers; correcting one teaches nothing transferable.
    """

    INTENT = "INTENT"
    CATEGORY = "CATEGORY"


def terms_in(*texts: str | None) -> tuple[str, ...]:
    """The learnable words in some text, in first-seen order and without repeats.

    Shared with `Correction.from_override` so that what is learned and what is looked up
    are normalised by the same function. Two normalisers would drift, and the failure would
    be silent: a lexicon that has learned a word it can never match again.
    """
    seen: dict[str, None] = {}
    for text in texts:
        if not text:
            continue
        for match in _WORD_RE.finditer(text.lower()):
            term = match.group(0).strip("'-")
            if MIN_TERM_LENGTH <= len(term) <= MAX_TERM_LENGTH and term not in STOPWORDS:
                seen.setdefault(term, None)
    return tuple(seen)


@dataclass(frozen=True, slots=True)
class Correction:
    """A person disagreeing with the machine, and the words they disagreed over.

    Constructed from a human override. There is no constructor that takes an inference,
    which is the point: this type is the only door into the lexicon, and a guess cannot
    walk through it.
    """

    family_id: FamilyId
    field: LexiconField
    corrected_to: str
    terms: tuple[str, ...]
    at: datetime

    def __post_init__(self) -> None:
        if not self.corrected_to.strip():
            raise ValueError("a correction has to be to something")
        if self.at.tzinfo is None:
            raise ValueError("a correction happened at a moment, and a moment has a timezone")

    @classmethod
    def from_override(
        cls,
        *,
        family_id: FamilyId,
        field: LexiconField,
        corrected_to: str,
        at: datetime,
        title: str | None = None,
        text: str | None = None,
        note: str | None = None,
    ) -> Correction:
        """The words of the thing that was corrected, in the order the engine sees them.

        `note` is the parent's own words about their own child and is the strongest signal
        in the product — which is exactly why it is passed here as text to be counted and
        never stored. What survives this call is a set of terms and a tally.
        """
        return cls(
            family_id=family_id,
            field=field,
            corrected_to=corrected_to.strip(),
            terms=terms_in(title, text, note),
            at=at,
        )


@dataclass(frozen=True, slots=True)
class Evidence:
    """How often this family has said this, and when they last did."""

    times: int
    last_at: datetime

    @property
    def speaks(self) -> bool:
        return self.times >= MIN_EVIDENCE_TO_SPEAK

    @property
    def weight(self) -> float:
        """Grows with use and stops. A family cannot shout the engine down by repetition."""
        return min(MAX_WEIGHT, float(self.times) * 0.5)

    def to_dict(self) -> dict[str, Any]:
        return {"times": self.times, "last_at": self.last_at.isoformat()}


#: (field, term, value) -> evidence. A flat key rather than nested dictionaries because
#: eviction and export both want to sort the whole thing, and nothing wants to walk it.
type Key = tuple[LexiconField, str, str]


@dataclass(frozen=True, slots=True)
class FamilyLexicon:
    """What one family's words mean, learned only from what that family corrected."""

    family_id: FamilyId
    entries: Mapping[Key, Evidence]

    @classmethod
    def empty(cls, family_id: FamilyId) -> FamilyLexicon:
        return cls(family_id=family_id, entries={})

    # ------------------------------------------------------------------ learn
    def learn(self, correction: Correction) -> Result[FamilyLexicon, DomainError]:
        """Count a correction against this family's own words.

        Refuses a correction from another family. Not because it would be a bug — because
        it would be the product this one exists not to be.
        """
        if correction.family_id != self.family_id:
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    "a lexicon learns from its own family and from nobody else",
                    {"lexicon": str(self.family_id), "correction": str(correction.family_id)},
                )
            )

        if not correction.terms:
            # A correction on a Spark with no words in it. Nothing was said, so nothing is
            # learned, and that is a success rather than an error.
            return Ok(self)

        updated = dict(self.entries)
        for term in correction.terms:
            key: Key = (correction.field, term, correction.corrected_to)
            seen = updated.get(key)
            updated[key] = Evidence(
                times=(seen.times if seen else 0) + 1,
                last_at=correction.at,
            )
        return Ok(FamilyLexicon(self.family_id, _within_bounds(updated)))

    # ----------------------------------------------------------------- recall
    def weights_for(self, field: LexiconField, terms: Iterable[str]) -> Mapping[str, float]:
        """What this family's usage says about these words, as weights per value.

        Empty is the common and correct answer. A term the family has corrected both ways
        contributes nothing at all — see `_unambiguous`.
        """
        totals: dict[str, float] = {}
        for term in terms:
            value = self._unambiguous(field, term)
            if value is None:
                continue
            evidence = self.entries[(field, term, value)]
            totals[value] = totals.get(value, 0.0) + evidence.weight
        return totals

    def _unambiguous(self, field: LexiconField, term: str) -> str | None:
        """The one value this family means by this word, if there is exactly one.

        Two values means this family uses the word both ways, and the honest answer is
        silence. Picking the higher count would make the product take a side in something
        the family has said twice is not one-sided.
        """
        speaking = [
            value
            for (entry_field, entry_term, value), evidence in self.entries.items()
            if entry_field is field and entry_term == term and evidence.speaks
        ]
        return speaking[0] if len(speaking) == 1 else None

    # ---------------------------------------------------------------- forget
    def forget(self, term: str) -> FamilyLexicon:
        """Unlearn one word, everywhere it appears. PRD 44: delete everything."""
        wanted = term.strip().lower()
        return FamilyLexicon(
            self.family_id,
            {key: evidence for key, evidence in self.entries.items() if key[1] != wanted},
        )

    def forget_everything(self) -> FamilyLexicon:
        return FamilyLexicon.empty(self.family_id)

    # ---------------------------------------------------------------- export
    def to_dict(self) -> dict[str, Any]:
        """Everything it knows, as plain data a family can read (PRD 44: export everything).

        Sorted, so two exports of the same lexicon are the same bytes and a family can
        diff last year's against this year's.
        """
        return {
            "family_id": str(self.family_id),
            "terms": [
                {
                    "field": field.value,
                    "term": term,
                    "means": value,
                    "speaks": evidence.speaks,
                    **evidence.to_dict(),
                }
                for (field, term, value), evidence in sorted(
                    self.entries.items(),
                    key=lambda item: (item[0][0].value, item[0][1], item[0][2]),
                )
            ],
        }

    def __len__(self) -> int:
        return len(self.entries)


def _within_bounds(entries: dict[Key, Evidence]) -> Mapping[Key, Evidence]:
    """Keep the strongest `MAX_TERMS`, so a lexicon stays a vocabulary and not an archive.

    Weakest and oldest first. The tiebreak is the key itself so that eviction is
    deterministic — a family's lexicon must not depend on dictionary ordering.
    """
    if len(entries) <= MAX_TERMS:
        return entries
    ranked = sorted(
        entries.items(),
        key=lambda item: (-item[1].times, -item[1].last_at.timestamp(), item[0][1], item[0][2]),
    )
    return dict(ranked[:MAX_TERMS])
