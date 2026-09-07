from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .memory import Memory, MemoryConfig, MemoryContextItem, register_memory, require
from .trajectory_store import materialize_prepared_trajectory, prepare_trajectory_insert


DEFAULT_BINARY = "codeagentcli"
DEFAULT_TIMEOUT_SECONDS = 1800.0
DEFAULT_INGEST_MAX_TURNS = 30
DEFAULT_QUERY_MAX_TURNS = 20
DEFAULT_MAX_ATTEMPTS = 3

INGEST_PROMPT = """This is a completed historical work session.

Read trajectory/trajectory.json and inspect screenshots only when useful. Identify environment knowledge that a future session could reuse, including UI state, workflows, environment-specific behavior, failure causes, limits, exceptions, and verified decisions.

The trajectory/ directory is temporary and will disappear after this session. Use your native auto-memory tools to save knowledge worth retaining across sessions. Do not merely summarize it in your final response: write valuable information into auto memory.

Save only claims directly supported by this trajectory. Do not add general knowledge or one-off progress. Update related memories instead of duplicating them. If a new observation conflicts with existing memory, retain source ordering and uncertainty rather than silently overwriting it.
"""

QUERY_PROMPT = """You are the memory retrieval component for a fixed downstream reader.

Use only auto memory formed by earlier historical sessions to find facts needed to answer question.json. The original trajectories are unavailable. Do not guess from general knowledge.

Return concise, direct, source-aware memory evidence. Preserve changes over time, conflicts, and uncertainty. If memory contains insufficient relevant information, return exactly: No relevant memory found.

Do not manufacture an answer from the question itself.
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _safe_name(value: str) -> str:
    readable = "".join(char if char.isalnum() or char in "-_." else "_" for char in value)[:80]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{readable or 'item'}_{digest}"


def _memory_snapshot(root: Path) -> dict[str, dict[str, Any]]:
    if not root.exists():
        return {}
    snapshot: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        stat = path.stat()
        snapshot[relative] = {
            "size": len(data),
            "mtime_ns": stat.st_mtime_ns,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    return snapshot


def _snapshot_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[str]]:
    before_paths = set(before)
    after_paths = set(after)
    return {
        "added": sorted(after_paths - before_paths),
        "modified": sorted(path for path in before_paths & after_paths if before[path] != after[path]),
        "deleted": sorted(before_paths - after_paths),
    }


def _parse_result(stdout: str) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            payload = json.loads(line.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict):
            events.append(payload)
    result = next((item for item in reversed(events) if item.get("type") == "result"), None)
    if result is None:
        return None, None, events
    text = result.get("result")
    usage = dict(result["usage"]) if isinstance(result.get("usage"), dict) else {}
    for key in ("num_turns", "total_cost_usd", "duration_api_ms", "duration_ms"):
        value = result.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            usage[key] = value
    return text if isinstance(text, str) else None, usage or None, events


@register_memory
class FreeCodeAutoMemory(Memory):
    memory_type = "free_code_auto_memory"

    def __init__(self, memory_params: dict[str, object]) -> None:
        super().__init__(memory_params)
        params_obj = memory_params.get("free_code_params", {})
        require(isinstance(params_obj, dict), "free_code_params must be an object")
        params = dict(params_obj)

        self.binary = Path(str(params.get("binary", DEFAULT_BINARY)))
        model = params.get("model")
        require(model is None or (isinstance(model, str) and model.strip()), "free_code model must be null or a non-empty string")
        self.model = model.strip() if isinstance(model, str) else None
        self.timeout_seconds = float(params.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
        self.ingest_max_turns = int(params.get("ingest_max_turns", DEFAULT_INGEST_MAX_TURNS))
        self.query_max_turns = int(params.get("query_max_turns", DEFAULT_QUERY_MAX_TURNS))
        self.max_attempts = int(params.get("max_retries", DEFAULT_MAX_ATTEMPTS))
        self.require_memory_write = params.get("require_memory_write", False)
        extra_args = params.get("extra_args", [])
        require(self.timeout_seconds > 0, "free_code timeout_seconds must be positive")
        require(self.ingest_max_turns > 0 and self.query_max_turns > 0, "free_code turn limits must be positive")
        require(self.max_attempts > 0, "free_code max_retries must be positive")
        require(isinstance(self.require_memory_write, bool), "free_code require_memory_write must be boolean")
        require(isinstance(extra_args, list) and all(isinstance(item, str) and item for item in extra_args), "free_code extra_args must be a list of non-empty strings")
        self.extra_args = list(extra_args)
        require(not any(item in {"--bare", "--resume", "-r", "--continue", "-c"} for item in self.extra_args), "free_code extra_args cannot enable bare or session continuation")

        workspace = memory_params.get("workspace_dir")
        trajectories_root = memory_params.get("trajectories_root_dir")
        self.workspace_dir = Path(str(workspace)).resolve() if workspace is not None else None
        self.trajectories_root_dir = Path(str(trajectories_root)).resolve() if trajectories_root is not None else None
        self.inserted_trajectory_ids: list[str] = []
        self.ingestion_records: list[dict[str, Any]] = []
        self.detected_version = self._detect_version()
        if self.workspace_dir is not None:
            self._ensure_layout()

    def _detect_version(self) -> str | None:
        try:
            result = subprocess.run([str(self.binary), "--version"], capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return (result.stdout or result.stderr).strip() or None

    @property
    def memory_config(self) -> MemoryConfig:
        params: dict[str, object] = {
            "binary": str(self.binary),
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "ingest_max_turns": self.ingest_max_turns,
            "query_max_turns": self.query_max_turns,
            "max_retries": self.max_attempts,
            "require_memory_write": self.require_memory_write,
            "extra_args": list(self.extra_args),
        }
        if self.detected_version is not None:
            params["detected_version"] = self.detected_version
        return {"memory_type": self.memory_type, "memory_params": {"free_code_params": params}}

    @classmethod
    def reconcile_loaded_memory_config(cls, saved_config: MemoryConfig, requested_config: MemoryConfig | None) -> MemoryConfig:
        if requested_config is None:
            return saved_config
        require(requested_config["memory_type"] == cls.memory_type, "Requested memory type does not match free_code_auto_memory")
        saved_params = dict(saved_config["memory_params"].get("free_code_params", {}))
        requested_params = dict(requested_config["memory_params"].get("free_code_params", {}))
        saved_params.pop("detected_version", None)
        requested_params.pop("detected_version", None)
        require(saved_params == requested_params, "free_code_auto_memory requested config does not match saved ingestion config")
        effective = {
            "memory_type": cls.memory_type,
            "memory_params": dict(requested_config["memory_params"]),
        }
        effective_free_code_params = dict(effective["memory_params"].get("free_code_params", {}))
        detected_version = saved_config["memory_params"].get("free_code_params", {}).get("detected_version")
        if detected_version is not None:
            effective_free_code_params["detected_version"] = detected_version
        effective["memory_params"]["free_code_params"] = effective_free_code_params
        return effective

    def _ensure_layout(self) -> None:
        require(self.workspace_dir is not None, "free_code_auto_memory requires workspace_dir")
        for name in ("auto_memory", "ingestion_sessions", "query_sessions"):
            (self.workspace_dir / name).mkdir(parents=True, exist_ok=True)

    def _command(self, prompt: str, max_turns: int) -> list[str]:
        command = [str(self.binary), "-p", "--output-format", "json", "--no-session-persistence", "--max-turns", str(max_turns), "--dangerously-skip-permissions"]
        if self.model is not None:
            command.extend(["--model", self.model])
        command.extend(self.extra_args)
        command.append(prompt)
        return command

    def _environment(self, memory_dir: Path, session_dir: Path) -> dict[str, str]:
        environment = dict(os.environ)
        environment["CODEAGENT3_COWORK_MEMORY_PATH_OVERRIDE"] = str(memory_dir.resolve())
        environment["CODEAGENT3_DISABLE_AUTO_MEMORY"] = "0"
        environment["CODEAGENT3_CONFIG_DIR"] = str((session_dir / "codeagent_config").resolve())
        environment.pop("CODEAGENT3_SIMPLE", None)
        return environment

    def _run(self, *, session_dir: Path, memory_dir: Path, prompt: str, max_turns: int) -> dict[str, Any]:
        command = self._command(prompt, max_turns)
        started = time.time()
        timed_out = False
        try:
            result = subprocess.run(command, cwd=session_dir, env=self._environment(memory_dir, session_dir), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=self.timeout_seconds, check=False)
            returncode, stdout, stderr = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = None
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        except OSError as exc:
            returncode, stdout, stderr = None, "", str(exc)
        (session_dir / "stdout.log").write_text(stdout, encoding="utf-8")
        (session_dir / "stderr.log").write_text(stderr, encoding="utf-8")
        text, usage, events = _parse_result(stdout)
        summary = {
            "command": command,
            "started_at_utc": datetime.fromtimestamp(started, timezone.utc).isoformat(),
            "completed_at_utc": _utc_now(),
            "duration_seconds": time.time() - started,
            "returncode": returncode,
            "timed_out": timed_out,
            "usage": usage,
            "result": text,
            "event_count": len(events),
        }
        return summary

    def insert(self, trajectory: dict[str, object]) -> None:
        require(self.workspace_dir is not None and self.trajectories_root_dir is not None, "free_code_auto_memory requires workspace_dir and trajectories_root_dir")
        prepared = prepare_trajectory_insert(trajectory, trajectories_root_dir=self.trajectories_root_dir)
        require(prepared.trajectory_id not in self.inserted_trajectory_ids, f"Duplicate trajectory id: {prepared.trajectory_id}")
        session_index = len(self.inserted_trajectory_ids)
        session_dir = self.workspace_dir / "ingestion_sessions" / f"{session_index:04d}_{_safe_name(prepared.trajectory_id)}"
        trajectory_dir = session_dir / "trajectory"
        materialize_prepared_trajectory(prepared, trajectory_dir)
        memory_dir = self.workspace_dir / "auto_memory"
        before = _memory_snapshot(memory_dir)
        summary = self._run(session_dir=session_dir, memory_dir=memory_dir, prompt=INGEST_PROMPT, max_turns=self.ingest_max_turns)
        after = _memory_snapshot(memory_dir)
        changes = _snapshot_diff(before, after)
        changed = any(changes.values())
        status = "success" if summary["returncode"] == 0 and changed else "empty_ingestion" if summary["returncode"] == 0 else "failed"
        summary.update({"trajectory_id": prepared.trajectory_id, "trajectory_fingerprint": prepared.fingerprint, "status": status, "memory_before": before, "memory_after": after, "memory_changes": changes})
        _write_json(session_dir / "summary.json", summary)
        self.inserted_trajectory_ids.append(prepared.trajectory_id)
        self.ingestion_records.append(summary)
        self._write_manifests()
        if self.require_memory_write and not changed:
            raise RuntimeError(f"CodeAgent made no auto-memory change for trajectory {prepared.trajectory_id}")

    def _write_manifests(self) -> None:
        require(self.workspace_dir is not None, "free_code_auto_memory requires workspace_dir")
        snapshot = _memory_snapshot(self.workspace_dir / "auto_memory")
        _write_json(self.workspace_dir / "ingestion_manifest.json", {"ordering_source": "haystack_order", "trajectory_ids": self.inserted_trajectory_ids, "records": self.ingestion_records, "updated_at_utc": _utc_now()})
        usage_totals: dict[str, float] = {}
        for record in self.ingestion_records:
            usage = record.get("usage")
            if not isinstance(usage, dict):
                continue
            for key, value in usage.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    usage_totals[key] = usage_totals.get(key, 0.0) + value
        _write_json(self.workspace_dir / "ingestion_metrics.json", {"trajectory_count": len(self.ingestion_records), "success_count": sum(item["status"] == "success" for item in self.ingestion_records), "empty_ingestion_count": sum(item["status"] == "empty_ingestion" for item in self.ingestion_records), "failed_count": sum(item["status"] == "failed" for item in self.ingestion_records), "total_duration_seconds": sum(float(item.get("duration_seconds", 0)) for item in self.ingestion_records), "usage_totals": usage_totals, "memory_file_count": len(snapshot), "memory_total_bytes": sum(item["size"] for item in snapshot.values()), "memory_snapshot": snapshot})

    def query(self, query: str, query_image: str | None = None) -> list[MemoryContextItem]:
        require(isinstance(query, str) and query.strip(), "free_code_auto_memory query must be non-empty")
        require(self.workspace_dir is not None, "free_code_auto_memory requires workspace_dir")
        invocation_id = self.get_query_context().get("query_invocation_id")
        require(isinstance(invocation_id, str) and invocation_id, "free_code_auto_memory query requires query_invocation_id")
        session_root = self.workspace_dir / "query_sessions" / _safe_name(invocation_id)
        source_memory = self.workspace_dir / "auto_memory"
        frozen_snapshot = _memory_snapshot(source_memory)
        last_summary: dict[str, Any] | None = None
        for attempt in range(1, self.max_attempts + 1):
            audit_dir = session_root / f"attempt_{attempt:03d}"
            audit_dir.parent.mkdir(parents=True, exist_ok=True)
            isolated_root = Path(tempfile.mkdtemp(prefix="longmemeval_free_code_query_"))
            session_dir = isolated_root / "session"
            session_dir.mkdir()
            memory_snapshot = session_dir / "auto_memory_snapshot"
            shutil.copytree(source_memory, memory_snapshot)
            question_payload: dict[str, Any] = {"question": query}
            if query_image is not None:
                source_image = Path(query_image)
                require(source_image.exists(), f"Missing query image: {source_image}")
                image_name = f"question_image{source_image.suffix or '.png'}"
                shutil.copy2(source_image, session_dir / image_name)
                question_payload["image"] = image_name
            _write_json(session_dir / "question.json", question_payload)
            summary = self._run(session_dir=session_dir, memory_dir=memory_snapshot, prompt=QUERY_PROMPT, max_turns=self.query_max_turns)
            summary.update({"query_invocation_id": invocation_id, "attempt": attempt, "main_memory_unchanged": _memory_snapshot(source_memory) == frozen_snapshot, "snapshot_after": _memory_snapshot(memory_snapshot)})
            _write_json(session_dir / "summary.json", summary)
            shutil.copytree(session_dir, audit_dir)
            shutil.rmtree(isolated_root)
            last_summary = summary
            result = summary.get("result")
            if summary["returncode"] == 0 and isinstance(result, str) and result.strip():
                require(_memory_snapshot(source_memory) == frozen_snapshot, "Query mutated frozen main auto memory")
                return [{"type": "text", "value": result.strip() + "\n"}]
        detail = last_summary or {}
        raise RuntimeError(f"CodeAgent auto-memory query failed after {self.max_attempts} attempts: returncode={detail.get('returncode')} timed_out={detail.get('timed_out')}")

    def _save_backend(self, output_dir: Path) -> None:
        require(self.workspace_dir is not None, "free_code_auto_memory requires workspace_dir")
        self._write_manifests()
        shutil.copytree(self.workspace_dir / "auto_memory", output_dir / "auto_memory", dirs_exist_ok=True)
        for filename in ("ingestion_manifest.json", "ingestion_metrics.json"):
            shutil.copy2(self.workspace_dir / filename, output_dir / filename)

    def _load_backend(self, input_dir: Path) -> None:
        require(self.workspace_dir is not None, "free_code_auto_memory load requires runtime workspace_dir")
        source_memory = input_dir / "auto_memory"
        require(source_memory.is_dir(), f"Missing saved auto_memory directory: {source_memory}")
        destination = self.workspace_dir / "auto_memory"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source_memory, destination)
        manifest = json.loads((input_dir / "ingestion_manifest.json").read_text(encoding="utf-8"))
        self.inserted_trajectory_ids = list(manifest.get("trajectory_ids", []))
        self.ingestion_records = list(manifest.get("records", []))
        self._write_manifests()
