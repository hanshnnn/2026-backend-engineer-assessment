"""Shared result types for the matcher."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

Decision = Literal["auto", "review", "reject"]


@dataclass(frozen=True)
class Candidate:
    item_code: str
    score: float

    def format(self) -> str:
        return f"{self.item_code}:{self.score:.4f}"


@dataclass
class MatchResult:
    """One decision for one order line (predictions.csv shape)."""

    decision: Decision
    reason_code: str
    item_code: str = ""
    confidence: float = 0.0
    candidates: list[Candidate] = field(default_factory=list)

    def candidates_csv(self) -> str:
        return "|".join(c.format() for c in self.candidates[:3])


@dataclass(frozen=True)
class TentativeHit:
    """Lane wants auto, pending ID arbitration / soft oppose."""

    item_code: str
    confidence: float
    reason_code: str
    candidates: tuple[Candidate, ...] = ()


@dataclass
class LaneOutcome:
    """Stop with a final result, carry a tentative auto, or continue."""

    result: Optional[MatchResult] = None
    tentative: Optional[TentativeHit] = None
    # OLD/disabled-only alias → live sibling; auto only if text candidates confirm.
    pending_text_confirm: Optional[TentativeHit] = None

    @property
    def stopped(self) -> bool:
        return self.result is not None
