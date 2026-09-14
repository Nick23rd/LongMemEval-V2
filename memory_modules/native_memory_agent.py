"""Common contract for evaluating an agent's native cross-session memory.

Concrete adapters live in this repository and treat the evaluated agent as a
black box.  They may invoke an open- or closed-source CLI/API, but must preserve
the lifecycle guarantees described by :class:`NativeMemoryAgent`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, ClassVar

from .memory import AgentAnswer, MEMORY_TYPES, MemoryConfig, StatefulMemory, require


@dataclass(frozen=True)
class NativeMemoryCapabilities:
    """Auditable capabilities supplied by a native-memory adapter."""

    trajectory_file_ingestion: bool
    fresh_query_session: bool
    frozen_memory_snapshot: bool
    historical_session_import: bool = False
    local_memory_state: bool = True

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


class NativeMemoryAgent(StatefulMemory, ABC):
    """Base class for black-box agents that own memory formation and recall.

    The harness owns trajectory selection, isolated workspaces, persistence and
    scoring.  A concrete adapter owns only product-specific invocation and
    native-memory access.  No change to the evaluated agent is required.
    """

    parameter_namespace: ClassVar[str]
    adapter_name: ClassVar[str]
    capabilities: ClassVar[NativeMemoryCapabilities]

    @abstractmethod
    def answer(
        self,
        question: str,
        question_image: str | None = None,
    ) -> AgentAnswer:
        """Answer in a fresh session using only the agent's native memory."""
        raise NotImplementedError

    @classmethod
    def inject_runtime_config(
        cls,
        memory_config: MemoryConfig,
        *,
        workspace_dir: Path,
        trajectories_path: str | None,
        query_trace_dir: Path | None,
    ) -> MemoryConfig:
        """Add run-local paths without persisting them in benchmark configs."""
        require(
            memory_config["memory_type"] == cls.memory_type,
            f"Runtime config type does not match {cls.memory_type}",
        )
        memory_params = dict(memory_config["memory_params"])
        memory_params["workspace_dir"] = str(workspace_dir.resolve())
        if trajectories_path is not None:
            memory_params["trajectories_root_dir"] = str(
                Path(trajectories_path).resolve().parent
            )
        if query_trace_dir is not None:
            memory_params["query_trace_dir"] = str(query_trace_dir.resolve())
        return {
            "memory_type": memory_config["memory_type"],
            "memory_params": memory_params,
        }

    @classmethod
    def config_resumes_build(cls, memory_config: MemoryConfig) -> bool:
        params = memory_config.get("memory_params")
        if not isinstance(params, dict):
            return False
        adapter_params = params.get(cls.parameter_namespace)
        return isinstance(adapter_params, dict) and adapter_params.get("resume_build") is True

    @classmethod
    def adapter_manifest(cls) -> dict[str, Any]:
        return {
            "name": cls.adapter_name,
            "memory_type": cls.memory_type,
            "black_box": True,
            "capabilities": cls.capabilities.to_dict(),
        }


def native_memory_class(memory_config: dict[str, Any] | None) -> type[NativeMemoryAgent] | None:
    """Return the registered native-memory adapter class for a config."""
    if not isinstance(memory_config, dict):
        return None
    memory_type = memory_config.get("memory_type")
    if not isinstance(memory_type, str):
        return None
    memory_cls = MEMORY_TYPES.get(memory_type)
    if memory_cls is None or not issubclass(memory_cls, NativeMemoryAgent):
        return None
    return memory_cls


def is_native_memory_config(memory_config: dict[str, Any] | None) -> bool:
    return native_memory_class(memory_config) is not None


def inject_native_memory_runtime_config(
    memory_config: MemoryConfig,
    *,
    workspace_dir: Path,
    trajectories_path: str | None,
    query_trace_dir: Path | None,
) -> MemoryConfig:
    memory_cls = native_memory_class(memory_config)
    require(memory_cls is not None, "Memory config is not a registered native-memory adapter")
    return memory_cls.inject_runtime_config(
        memory_config,
        workspace_dir=workspace_dir,
        trajectories_path=trajectories_path,
        query_trace_dir=query_trace_dir,
    )
