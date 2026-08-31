"""The Safe Vault (PRD 48 F5, PRD 21, PRD 50).

    "Everything captured should remain searchable ... No complex folder management."

Retrieval works off what the thing is, who it is for, and what the parent meant to do with it.
Search utilizes text queries expanded by the family's private FamilyLexicon synonyms.
Visibility is applied before results are returned, so a search can never bypass the
permission model (PRD 44, 45).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from anuvritti.application.ports import FamilyRepository, LexiconRepository, SparkRepository
from anuvritti.domain.constellation import Constellation, ConstellationClusterer
from anuvritti.domain.lexicon import LexiconField
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import IntentType, SparkStatus
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, MemberId
from anuvritti.shared.result import Err, Ok, Result

DEFAULT_LIMIT: Final = 25


@dataclass(frozen=True, slots=True)
class SearchVaultQuery:
    family_id: FamilyId
    actor_id: MemberId
    text: str | None = None
    intent: IntentType | None = None
    child_id: ChildId | None = None
    age_years: int | None = None
    status: SparkStatus | None = None
    use_child_age: bool = False
    limit: int = DEFAULT_LIMIT


class SearchVaultUseCase:
    """Find the thing you half-remember saving."""

    MAX_LIMIT: Final = 100

    def __init__(
        self,
        *,
        families: FamilyRepository,
        sparks: SparkRepository,
        clock: Clock,
        lexicons: LexiconRepository | None = None,
    ) -> None:
        self._families = families
        self._sparks = sparks
        self._clock = clock
        self._lexicons = lexicons

    def execute(self, query: SearchVaultQuery) -> Result[Sequence[Spark], DomainError]:
        if query.limit < 1:
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, "limit must be at least 1"))

        family_result = self._families.get(query.family_id)
        if family_result.is_err():
            return Err(family_result.unwrap_err())
        family = family_result.unwrap()

        actor_result = family.member(query.actor_id)
        if actor_result.is_err():
            return Err(actor_result.unwrap_err())
        actor = actor_result.unwrap()

        age_years = query.age_years
        if query.use_child_age and query.child_id is not None:
            child_result = family.child(query.child_id)
            if child_result.is_err():
                return Err(child_result.unwrap_err())
            age_years = child_result.unwrap().age_years(self._clock.today())

        search_intent = query.intent
        search_text = query.text

        # If text is provided and lexicon repository is available, expand with family synonyms
        if search_text and self._lexicons and search_intent is None:
            lex_res = self._lexicons.load(query.family_id)
            if lex_res.is_ok():
                lex = lex_res.unwrap()
                words = search_text.lower().split()
                for word in words:
                    val = lex._unambiguous(LexiconField.INTENT, word)
                    if val:
                        try:
                            search_intent = IntentType(val)
                            if len(words) == 1:
                                search_text = None
                            break
                        except ValueError:
                            pass

        found = self._sparks.search(
            query.family_id,
            text=search_text,
            intent=search_intent,
            child_id=query.child_id,
            age_years=age_years,
            status=query.status,
            limit=min(query.limit, self.MAX_LIMIT),
        )
        if found.is_err():
            return Err(found.unwrap_err())

        # Visibility is enforced here, not in the query, so no adapter can forget it.
        return Ok([s for s in found.unwrap() if s.visibility.is_visible_to(actor.role)])

    def cluster_constellations(
        self, sparks: Sequence[Spark], *, at: datetime | None = None
    ) -> list[Constellation]:
        """TASK-802: Organically cluster sparks into emergent constellations."""
        now = at if at is not None else self._clock.now()
        return ConstellationClusterer.cluster(sparks, at=now)
