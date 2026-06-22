"""In-memory historical case store for tests."""

from __future__ import annotations

from schemas.memory import SimilarCase


class InMemoryVectorMemoryStore:
    """Process-local case store with deterministic score ordering."""

    def __init__(self) -> None:
        self._cases: list[SimilarCase] = []

    def add_case(self, case: SimilarCase) -> None:
        """Store a historical case."""

        self._cases.append(case.model_copy(deep=True))

    def search_similar_cases(self, user_question: str, limit: int = 5) -> list[SimilarCase]:
        """Return stored cases ordered by score without doing vector search."""

        _ = user_question
        ordered_cases = sorted(
            self._cases,
            key=lambda case: -1 if case.score is None else case.score,
            reverse=True,
        )
        return [case.model_copy(deep=True) for case in ordered_cases[:limit]]
