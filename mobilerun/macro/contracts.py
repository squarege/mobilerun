"""Public contracts for guarded macro execution and recovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class RecoveryOutcome:
    """Structured result returned by a scoped recovery agent."""

    status: str
    reason: str = ""
    checkpoint: Optional[int] = None
    agent_actions: int = 0
    llm_calls: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def recovered_to_same_step(
        cls, *, reason: str = "", agent_actions: int = 0, llm_calls: int = 1, **metadata
    ) -> "RecoveryOutcome":
        return cls(
            status="RECOVERED_TO_SAME_STEP",
            reason=reason,
            agent_actions=agent_actions,
            llm_calls=llm_calls,
            metadata=metadata,
        )

    @classmethod
    def recovered_to_checkpoint(
        cls,
        checkpoint: int,
        *,
        reason: str = "",
        agent_actions: int = 0,
        llm_calls: int = 1,
        **metadata,
    ) -> "RecoveryOutcome":
        return cls(
            status="RECOVERED_TO_CHECKPOINT",
            reason=reason,
            checkpoint=checkpoint,
            agent_actions=agent_actions,
            llm_calls=llm_calls,
            metadata=metadata,
        )

    @classmethod
    def needs_human(
        cls,
        reason: str,
        *,
        agent_actions: int = 0,
        llm_calls: int = 0,
        **metadata,
    ) -> "RecoveryOutcome":
        return cls(
            status="NEEDS_HUMAN",
            reason=reason,
            agent_actions=agent_actions,
            llm_calls=llm_calls,
            metadata=metadata,
        )

    @classmethod
    def unrecoverable(
        cls,
        reason: str,
        *,
        agent_actions: int = 0,
        llm_calls: int = 0,
        **metadata,
    ) -> "RecoveryOutcome":
        return cls(
            status="UNRECOVERABLE",
            reason=reason,
            agent_actions=agent_actions,
            llm_calls=llm_calls,
            metadata=metadata,
        )

    @classmethod
    def unknown_outcome(
        cls,
        reason: str,
        *,
        agent_actions: int = 0,
        llm_calls: int = 0,
        **metadata,
    ) -> "RecoveryOutcome":
        return cls(
            status="UNKNOWN_OUTCOME",
            reason=reason,
            agent_actions=agent_actions,
            llm_calls=llm_calls,
            metadata=metadata,
        )

    @property
    def recovered(self) -> bool:
        return self.status in {"RECOVERED_TO_SAME_STEP", "RECOVERED_TO_CHECKPOINT"}


@dataclass
class RunResult:
    """Machine-readable result for one macro/workflow run."""

    status: str
    total_steps: int = 0
    steps_completed: int = 0
    llm_calls: int = 0
    recovery_attempts: int = 0
    last_verified_checkpoint: int = -1
    failure_reason: Optional[str] = None
    journal_path: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status in {
            "MACRO_SUCCESS",
            "RECOVERED_AND_RESUMED",
            "FALLBACK_COMPLETED",
        }

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "total_steps": self.total_steps,
            "steps_completed": self.steps_completed,
            "llm_calls": self.llm_calls,
            "recovery_attempts": self.recovery_attempts,
            "last_verified_checkpoint": self.last_verified_checkpoint,
            "failure_reason": self.failure_reason,
            "journal_path": self.journal_path,
            "details": self.details,
        }
