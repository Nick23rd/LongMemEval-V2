"""Shared orchestration for stateful memory build lifecycles."""

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from memory_modules.memory import StatefulMemory


@dataclass(frozen=True)
class IngestionPlan:
    trajectory_ids: list[str]
    metadata: dict[str, object]


def resolve_ingestion_plan(trajectory_ids: Iterable[str]) -> IngestionPlan:
    """Preserve benchmark order when the dataset has no cross-trajectory timestamps."""
    ids = list(trajectory_ids)
    return IngestionPlan(
        trajectory_ids=ids,
        metadata={
            "ordering_source": "haystack_order",
            "timestamp_fields_checked": [],
            "timestamp_field_used": None,
            "reason": (
                "The LongMemEval-V2 trajectory schema has no cross-trajectory "
                "timestamp; the benchmark-provided order is authoritative."
            ),
        },
    )


def build_stateful_memory(
    memory: StatefulMemory,
    trajectory_ids: Iterable[str],
    trajectories: dict[str, dict[str, Any]],
    *,
    progress: Callable[[Iterable[str]], Iterable[str]] | None = None,
) -> IngestionPlan:
    """Build and finalize a stateful backend through one explicit lifecycle."""
    plan = resolve_ingestion_plan(trajectory_ids)
    memory.configure_ingestion_plan(plan.metadata)
    missing = [trajectory_id for trajectory_id in plan.trajectory_ids if trajectory_id not in trajectories]
    if missing:
        raise RuntimeError(f"Missing trajectory id in trajectories data: {missing[0]}")
    if memory.insert_many(plan.trajectory_ids, trajectories):
        memory.finalize_build()
        return plan
    iterable = progress(plan.trajectory_ids) if progress is not None else plan.trajectory_ids
    for trajectory_id in iterable:
        memory.insert(trajectories[trajectory_id])
    memory.finalize_build()
    return plan
