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

from .memory import AgentAnswer, MemoryConfig, MemoryContextItem, StatefulMemory, register_memory, require
from .trajectory_store import materialize_prepared_trajectory, prepare_trajectory_insert


DEFAULT_BINARY = "codeagentcli"
DEFAULT_TIMEOUT_SECONDS = 1800.0
DEFAULT_INGEST_MAX_TURNS = 30
DEFAULT_QUERY_MAX_TURNS = 20
DEFAULT_INGEST_MAX_ATTEMPTS = 1
DEFAULT_QUERY_MAX_ATTEMPTS = 3
DEFAULT_EXPERIMENT_MODE = "baseline"
EXPERIMENT_MODES = {"memory_off", "baseline", "candidate"}

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

DIRECT_ANSWER_PROMPT = """Answer the question in question.json directly.

Use only your native auto memory formed by earlier historical work sessions. The original trajectories are unavailable. Do not guess from general knowledge.

Follow the output-format instruction in the question exactly. If the relevant information is not available in your memory, return exactly: \\boxed{UNKNOWN}

Do not describe memory retrieval and do not return a separate evidence section. Your result is the final answer that will be scored.
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
        snapshot[relative] = {
            "size": len(data),
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


def _snapshot_digest(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(snapshot, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _replace_tree(source: Path, destination: Path) -> None:
    replacement = destination.with_name(destination.name + ".replacement")
    backup = destination.with_name(destination.name + ".backup")
    if replacement.exists():
        shutil.rmtree(replacement)
    if backup.exists():
        shutil.rmtree(backup)
    shutil.copytree(source, replacement)
    destination.replace(backup)
    try:
        replacement.replace(destination)
    except BaseException:
        backup.replace(destination)
        raise
    shutil.rmtree(backup)


def _copy_audit_files(session_dir: Path, audit_dir: Path) -> None:
    """Keep reproducibility logs without duplicating every memory snapshot."""
    audit_dir.mkdir(parents=True, exist_ok=False)
    for filename in ("stdout.log", "stderr.log", "summary.json", "question.json"):
        source = session_dir / filename
        if source.exists():
            shutil.copy2(source, audit_dir / filename)
    trajectory_json = session_dir / "trajectory" / "trajectory.json"
    if trajectory_json.exists():
        target = audit_dir / "trajectory" / "trajectory.json"
        target.parent.mkdir(parents=True)
        shutil.copy2(trajectory_json, target)


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
class CodeAgentAutoMemory(StatefulMemory):
    memory_type = "codeagent_auto_memory"

    def __init__(self, memory_params: dict[str, object]) -> None:
        super().__init__(memory_params)
        params_obj = memory_params.get("codeagent_auto_memory_params", {})
        require(isinstance(params_obj, dict), "codeagent_auto_memory_params must be an object")
        params = dict(params_obj)

        self.binary = Path(str(params.get("binary", DEFAULT_BINARY)))
        model = params.get("model")
        require(model is None or (isinstance(model, str) and model.strip()), "codeagent auto-memory model must be null or a non-empty string")
        self.model = model.strip() if isinstance(model, str) else None
        self.timeout_seconds = float(params.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
        self.ingest_max_turns = int(params.get("ingest_max_turns", DEFAULT_INGEST_MAX_TURNS))
        self.query_max_turns = int(params.get("query_max_turns", DEFAULT_QUERY_MAX_TURNS))
        self.ingest_max_attempts = int(params.get("ingest_max_attempts", DEFAULT_INGEST_MAX_ATTEMPTS))
        self.query_max_attempts = int(params.get("query_max_attempts", DEFAULT_QUERY_MAX_ATTEMPTS))
        experiment_mode = params.get("experiment_mode", DEFAULT_EXPERIMENT_MODE)
        require(
            isinstance(experiment_mode, str) and experiment_mode in EXPERIMENT_MODES,
            f"codeagent auto-memory experiment_mode must be one of {sorted(EXPERIMENT_MODES)}",
        )
        self.experiment_mode = experiment_mode
        version_label = params.get("version_label")
        require(
            version_label is None or (isinstance(version_label, str) and version_label.strip()),
            "codeagent auto-memory version_label must be null or a non-empty string",
        )
        self.version_label = version_label.strip() if isinstance(version_label, str) else None
        self.ingest_prompt = self._resolve_prompt(params, "ingest_prompt", INGEST_PROMPT)
        self.query_prompt = self._resolve_prompt(params, "query_prompt", QUERY_PROMPT)
        self.direct_answer_prompt = self._resolve_prompt(
            params, "direct_answer_prompt", DIRECT_ANSWER_PROMPT
        )
        supplied_hashes = params.get("prompt_hashes")
        if supplied_hashes is not None:
            require(isinstance(supplied_hashes, dict), "prompt_hashes must be an object")
            require(
                supplied_hashes
                == {name: item["sha256"] for name, item in self._prompt_manifest().items()},
                "Saved prompt hashes do not match the configured prompt text",
            )
        self.require_memory_write = params.get("require_memory_write", False)
        self.resume_build = params.get("resume_build", False)
        extra_args = params.get("extra_args", [])
        require(self.timeout_seconds > 0, "codeagent auto-memory timeout_seconds must be positive")
        require(self.ingest_max_turns > 0 and self.query_max_turns > 0, "codeagent auto-memory turn limits must be positive")
        require(self.ingest_max_attempts > 0 and self.query_max_attempts > 0, "codeagent auto-memory attempt limits must be positive")
        require(isinstance(self.require_memory_write, bool), "codeagent auto-memory require_memory_write must be boolean")
        require(
            self.experiment_mode != "memory_off" or not self.require_memory_write,
            "memory_off cannot require an auto-memory write",
        )
        require(isinstance(self.resume_build, bool), "codeagent auto-memory resume_build must be boolean")
        require(isinstance(extra_args, list) and all(isinstance(item, str) and item for item in extra_args), "codeagent auto-memory extra_args must be a list of non-empty strings")
        self.extra_args = list(extra_args)
        require(not any(item in {"--bare", "--resume", "-r", "--continue", "-c", "--dangerously-skip-permissions"} for item in self.extra_args), "codeagent auto-memory extra_args cannot weaken isolation or continue sessions")

        workspace = memory_params.get("workspace_dir")
        trajectories_root = memory_params.get("trajectories_root_dir")
        self.workspace_dir = Path(str(workspace)).resolve() if workspace is not None else None
        self.trajectories_root_dir = Path(str(trajectories_root)).resolve() if trajectories_root is not None else None
        self.inserted_trajectory_ids: list[str] = []
        self.ingestion_records: list[dict[str, Any]] = []
        self.ingestion_plan: dict[str, object] = {
            "ordering_source": "unspecified",
            "timestamp_fields_checked": [],
            "timestamp_field_used": None,
        }
        self.detected_version = self._detect_version()
        if self.workspace_dir is not None:
            self._ensure_layout()
            self._restore_checkpoint()

    @staticmethod
    def _resolve_prompt(params: dict[str, object], key: str, default: str) -> str:
        value = params.get(key, default)
        require(
            isinstance(value, str) and value.strip(),
            f"codeagent auto-memory {key} must be a non-empty string",
        )
        return value

    def _prompt_manifest(self) -> dict[str, dict[str, str]]:
        return {
            "ingest": {"text": self.ingest_prompt, "sha256": _text_digest(self.ingest_prompt)},
            "query": {"text": self.query_prompt, "sha256": _text_digest(self.query_prompt)},
            "direct_answer": {
                "text": self.direct_answer_prompt,
                "sha256": _text_digest(self.direct_answer_prompt),
            },
        }

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
            "ingest_max_attempts": self.ingest_max_attempts,
            "query_max_attempts": self.query_max_attempts,
            "experiment_mode": self.experiment_mode,
            "version_label": self.version_label,
            "ingest_prompt": self.ingest_prompt,
            "query_prompt": self.query_prompt,
            "direct_answer_prompt": self.direct_answer_prompt,
            "prompt_hashes": {
                name: item["sha256"] for name, item in self._prompt_manifest().items()
            },
            "require_memory_write": self.require_memory_write,
            "resume_build": self.resume_build,
            "extra_args": list(self.extra_args),
        }
        if self.detected_version is not None:
            params["detected_version"] = self.detected_version
        return {"memory_type": self.memory_type, "memory_params": {"codeagent_auto_memory_params": params}}

    @classmethod
    def reconcile_loaded_memory_config(cls, saved_config: MemoryConfig, requested_config: MemoryConfig | None) -> MemoryConfig:
        if requested_config is None:
            return saved_config
        require(requested_config["memory_type"] == cls.memory_type, "Requested memory type does not match codeagent_auto_memory")
        saved_params = dict(saved_config["memory_params"].get("codeagent_auto_memory_params", {}))
        requested_params = dict(requested_config["memory_params"].get("codeagent_auto_memory_params", {}))
        saved_params.pop("detected_version", None)
        requested_params.pop("detected_version", None)
        saved_params.pop("resume_build", None)
        requested_params.pop("resume_build", None)
        saved_params.pop("prompt_hashes", None)
        requested_params.pop("prompt_hashes", None)
        for key, default in (
            ("experiment_mode", DEFAULT_EXPERIMENT_MODE),
            ("version_label", None),
            ("ingest_prompt", INGEST_PROMPT),
            ("query_prompt", QUERY_PROMPT),
            ("direct_answer_prompt", DIRECT_ANSWER_PROMPT),
        ):
            saved_params.setdefault(key, default)
            requested_params.setdefault(key, default)
        require(saved_params == requested_params, "codeagent_auto_memory requested config does not match saved ingestion config")
        effective = {
            "memory_type": cls.memory_type,
            "memory_params": dict(requested_config["memory_params"]),
        }
        effective_params = dict(effective["memory_params"].get("codeagent_auto_memory_params", {}))
        detected_version = saved_config["memory_params"].get("codeagent_auto_memory_params", {}).get("detected_version")
        if detected_version is not None:
            effective_params["detected_version"] = detected_version
        effective["memory_params"]["codeagent_auto_memory_params"] = effective_params
        return effective

    def _ensure_layout(self) -> None:
        require(self.workspace_dir is not None, "codeagent_auto_memory requires workspace_dir")
        for name in ("auto_memory", "ingestion_sessions", "query_sessions", "answer_sessions"):
            (self.workspace_dir / name).mkdir(parents=True, exist_ok=True)

    def _restore_checkpoint(self) -> None:
        require(self.workspace_dir is not None, "codeagent_auto_memory requires workspace_dir")
        manifest_path = self.workspace_dir / "ingestion_manifest.json"
        if not manifest_path.exists():
            return
        require(self.resume_build, f"Existing auto-memory build requires resume_build=true: {self.workspace_dir}")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(payload.get("memory_type") == self.memory_type, "Checkpoint memory type mismatch")
        self.inserted_trajectory_ids = list(payload.get("trajectory_ids", []))
        self.ingestion_records = list(payload.get("records", []))
        self.ingestion_plan = dict(payload.get("ingestion_plan", self.ingestion_plan))

    def configure_ingestion_plan(self, metadata: dict[str, object]) -> None:
        self.ingestion_plan = dict(metadata)

    def _command(self, prompt: str, max_turns: int, *, ingestion: bool) -> list[str]:
        command = [str(self.binary), "-p", "--output-format", "json", "--no-session-persistence", "--max-turns", str(max_turns)]
        if ingestion:
            command.extend(["--permission-mode", "acceptEdits", "--tools=Read,Write,Edit,Glob,Grep"])
        else:
            # Native auto-memory injects an index, then asks the agent to read
            # the selected memory file. Keep queries read-only rather than
            # disabling every tool.
            command.extend(["--permission-mode", "dontAsk", "--tools=Read"])
        if self.model is not None:
            command.extend(["--model", self.model])
        command.extend(self.extra_args)
        command.append(prompt)
        return command

    def _environment(self, memory_dir: Path) -> dict[str, str]:
        environment = dict(os.environ)
        environment["CODEAGENT3_COWORK_MEMORY_PATH_OVERRIDE"] = str(memory_dir.resolve())
        environment["CODEAGENT3_DISABLE_AUTO_MEMORY"] = (
            "1" if self.experiment_mode == "memory_off" else "0"
        )
        # Inherit the configured CodeAgent config so its selected model and
        # credentials remain available. Session isolation is provided by the
        # temporary cwd plus --no-session-persistence; memory is independently
        # redirected to the frozen per-call snapshot above.
        environment.pop("CODEAGENT3_SIMPLE", None)
        return environment

    def _run(self, *, session_dir: Path, memory_dir: Path, prompt: str, max_turns: int, ingestion: bool) -> dict[str, Any]:
        command = self._command(prompt, max_turns, ingestion=ingestion)
        started = time.time()
        timed_out = False
        try:
            result = subprocess.run(command, cwd=session_dir, env=self._environment(memory_dir), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=self.timeout_seconds, check=False)
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
        require(self.workspace_dir is not None and self.trajectories_root_dir is not None, "codeagent_auto_memory requires workspace_dir and trajectories_root_dir")
        prepared = prepare_trajectory_insert(trajectory, trajectories_root_dir=self.trajectories_root_dir)
        if prepared.trajectory_id in self.inserted_trajectory_ids:
            previous = next(item for item in reversed(self.ingestion_records) if item.get("trajectory_id") == prepared.trajectory_id and item.get("status") in {"success", "empty_ingestion"})
            require(previous.get("trajectory_fingerprint") == prepared.fingerprint, f"Checkpoint trajectory changed: {prepared.trajectory_id}")
            return
        session_index = len(self.inserted_trajectory_ids)
        main_memory = self.workspace_dir / "auto_memory"
        before = _memory_snapshot(main_memory)
        if self.experiment_mode == "memory_off":
            require(not before, "memory_off requires an empty persistent memory directory")
        final_record: dict[str, Any] | None = None
        for attempt in range(1, self.ingest_max_attempts + 1):
            audit_dir = self.workspace_dir / "ingestion_sessions" / f"{session_index:04d}_{_safe_name(prepared.trajectory_id)}" / f"attempt_{attempt:03d}"
            isolated_root = Path(tempfile.mkdtemp(prefix="longmemeval_codeagent_ingest_"))
            session_dir = isolated_root / "session"
            session_dir.mkdir()
            isolated_memory = session_dir / "auto_memory"
            shutil.copytree(main_memory, isolated_memory)
            materialize_prepared_trajectory(prepared, session_dir / "trajectory")
            summary = self._run(session_dir=session_dir, memory_dir=isolated_memory, prompt=self.ingest_prompt, max_turns=self.ingest_max_turns, ingestion=True)
            after = _memory_snapshot(isolated_memory)
            changes = _snapshot_diff(before, after)
            changed = any(changes.values())
            if summary["returncode"] != 0:
                status = "failed"
            elif self.experiment_mode == "memory_off" and changed:
                status = "isolation_failed"
            elif self.experiment_mode == "memory_off":
                status = "success"
            elif changed:
                status = "success"
            else:
                status = "empty_ingestion"
            summary.update({"trajectory_id": prepared.trajectory_id, "trajectory_fingerprint": prepared.fingerprint, "attempt": attempt, "status": status, "memory_before_digest": _snapshot_digest(before), "memory_after_digest": _snapshot_digest(after), "memory_changes": changes})
            _write_json(session_dir / "summary.json", summary)
            audit_dir.parent.mkdir(parents=True, exist_ok=True)
            _copy_audit_files(session_dir, audit_dir)
            if summary["returncode"] == 0 and self.experiment_mode != "memory_off":
                _replace_tree(isolated_memory, main_memory)
            shutil.rmtree(isolated_root)
            self.ingestion_records.append(summary)
            final_record = summary
            manifest_status = (
                "isolation_failed"
                if status == "isolation_failed"
                else "building"
                if summary["returncode"] == 0
                else "partial_failed"
            )
            self._write_manifests(status=manifest_status)
            if status in {"success", "empty_ingestion", "isolation_failed"}:
                break
        require(final_record is not None, "CodeAgent ingestion produced no attempt record")
        if final_record["status"] == "failed":
            raise RuntimeError(f"CodeAgent ingestion failed for trajectory {prepared.trajectory_id} after {self.ingest_max_attempts} attempts")
        if final_record["status"] == "isolation_failed":
            raise RuntimeError(
                f"CodeAgent wrote auto-memory while experiment_mode=memory_off for trajectory {prepared.trajectory_id}"
            )
        if self.require_memory_write and final_record["status"] == "empty_ingestion":
            raise RuntimeError(f"CodeAgent made no auto-memory change for trajectory {prepared.trajectory_id}")
        self.inserted_trajectory_ids.append(prepared.trajectory_id)
        self._write_manifests(status="building")

    def _write_manifests(self, *, status: str = "building") -> None:
        require(self.workspace_dir is not None, "codeagent_auto_memory requires workspace_dir")
        snapshot = _memory_snapshot(self.workspace_dir / "auto_memory")
        _write_json(self.workspace_dir / "ingestion_manifest.json", {"memory_type": self.memory_type, "experiment_mode": self.experiment_mode, "version_label": self.version_label, "detected_version": self.detected_version, "binary": str(self.binary.resolve()), "prompt_hashes": {name: item["sha256"] for name, item in self._prompt_manifest().items()}, "build_status": status, "ingestion_plan": self.ingestion_plan, "trajectory_ids": self.inserted_trajectory_ids, "records": self.ingestion_records, "memory_snapshot_digest": _snapshot_digest(snapshot), "updated_at_utc": _utc_now()})
        _write_json(self.workspace_dir / "prompt_manifest.json", self._prompt_manifest())
        usage_totals: dict[str, float] = {}
        for record in self.ingestion_records:
            usage = record.get("usage")
            if not isinstance(usage, dict):
                continue
            for key, value in usage.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    usage_totals[key] = usage_totals.get(key, 0.0) + value
        final_records = [next(item for item in reversed(self.ingestion_records) if item.get("trajectory_id") == trajectory_id) for trajectory_id in self.inserted_trajectory_ids]
        _write_json(self.workspace_dir / "ingestion_metrics.json", {"trajectory_count": len(self.inserted_trajectory_ids), "attempt_count": len(self.ingestion_records), "success_count": sum(item["status"] == "success" for item in final_records), "empty_ingestion_count": sum(item["status"] == "empty_ingestion" for item in final_records), "failed_attempt_count": sum(item["status"] == "failed" for item in self.ingestion_records), "total_duration_seconds": sum(float(item.get("duration_seconds", 0)) for item in self.ingestion_records), "usage_totals": usage_totals, "memory_file_count": len(snapshot), "memory_total_bytes": sum(item["size"] for item in snapshot.values()), "memory_snapshot": snapshot})

    def finalize_build(self) -> None:
        if self.experiment_mode == "memory_off":
            require(
                self.workspace_dir is not None and not _memory_snapshot(self.workspace_dir / "auto_memory"),
                "memory_off build produced persistent auto-memory",
            )
            status = "complete_memory_off"
        else:
            status = "complete_with_empty_ingestions" if any(item.get("status") == "empty_ingestion" for item in self.ingestion_records) else "complete"
        self._write_manifests(status=status)

    def build_metrics(self) -> dict[str, object] | None:
        if self.workspace_dir is None:
            return None
        path = self.workspace_dir / "ingestion_metrics.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def query(self, query: str, query_image: str | None = None) -> list[MemoryContextItem]:
        summary = self._run_frozen_memory_question(
            query=query,
            query_image=query_image,
            prompt=self.query_prompt,
            session_kind="query",
        )
        result = summary["result"]
        require(isinstance(result, str), "CodeAgent query result must be text")
        return [{"type": "text", "value": result.strip() + "\n"}]

    def answer(self, question: str, question_image: str | None = None) -> AgentAnswer:
        """Answer directly in a fresh session using the frozen native memory."""
        summary = self._run_frozen_memory_question(
            query=question,
            query_image=question_image,
            prompt=self.direct_answer_prompt,
            session_kind="answer",
        )
        response_raw = summary["result"]
        assert isinstance(response_raw, str)
        return {
            "response_raw": response_raw.strip(),
            "usage": summary.get("usage") if isinstance(summary.get("usage"), dict) else None,
            "duration_seconds": float(summary.get("duration_seconds", 0.0)),
            "metadata": {
                "experiment_mode": self.experiment_mode,
                "query_invocation_id": summary["query_invocation_id"],
                "attempt": summary["attempt"],
                "main_memory_unchanged": summary["main_memory_unchanged"],
            },
        }

    def _run_frozen_memory_question(
        self,
        *,
        query: str,
        query_image: str | None,
        prompt: str,
        session_kind: str,
    ) -> dict[str, Any]:
        require(isinstance(query, str) and query.strip(), "codeagent_auto_memory query must be non-empty")
        require(self.workspace_dir is not None, "codeagent_auto_memory requires workspace_dir")
        require(session_kind in {"query", "answer"}, f"Unsupported session kind: {session_kind}")
        invocation_id = self.get_query_context().get("query_invocation_id")
        require(isinstance(invocation_id, str) and invocation_id, "codeagent_auto_memory query requires query_invocation_id")
        session_root = self.workspace_dir / f"{session_kind}_sessions" / _safe_name(invocation_id)
        source_memory = self.workspace_dir / "auto_memory"
        frozen_snapshot = _memory_snapshot(source_memory)
        last_summary: dict[str, Any] | None = None
        for attempt in range(1, self.query_max_attempts + 1):
            audit_dir = session_root / f"attempt_{attempt:03d}"
            audit_dir.parent.mkdir(parents=True, exist_ok=True)
            isolated_root = Path(tempfile.mkdtemp(prefix="longmemeval_codeagent_query_"))
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
            summary = self._run(session_dir=session_dir, memory_dir=memory_snapshot, prompt=prompt, max_turns=self.query_max_turns, ingestion=False)
            summary.update({"query_invocation_id": invocation_id, "session_kind": session_kind, "attempt": attempt, "main_memory_unchanged": _memory_snapshot(source_memory) == frozen_snapshot, "snapshot_after": _memory_snapshot(memory_snapshot)})
            _write_json(session_dir / "summary.json", summary)
            _copy_audit_files(session_dir, audit_dir)
            shutil.rmtree(isolated_root)
            last_summary = summary
            result = summary.get("result")
            if summary["returncode"] == 0 and isinstance(result, str) and result.strip():
                require(_memory_snapshot(source_memory) == frozen_snapshot, "Query mutated frozen main auto memory")
                if self.experiment_mode == "memory_off":
                    require(not summary["snapshot_after"], "CodeAgent wrote auto-memory during a memory_off query")
                return summary
        detail = last_summary or {}
        raise RuntimeError(f"CodeAgent auto-memory query failed after {self.query_max_attempts} attempts: returncode={detail.get('returncode')} timed_out={detail.get('timed_out')}")

    def _save_backend(self, output_dir: Path) -> None:
        require(self.workspace_dir is not None, "codeagent_auto_memory requires workspace_dir")
        self.finalize_build()
        shutil.copytree(self.workspace_dir / "auto_memory", output_dir / "auto_memory", dirs_exist_ok=True)
        for filename in ("ingestion_manifest.json", "ingestion_metrics.json", "prompt_manifest.json"):
            shutil.copy2(self.workspace_dir / filename, output_dir / filename)

    def _load_backend(self, input_dir: Path) -> None:
        require(self.workspace_dir is not None, "codeagent_auto_memory load requires runtime workspace_dir")
        source_memory = input_dir / "auto_memory"
        require(source_memory.is_dir(), f"Missing saved auto_memory directory: {source_memory}")
        destination = self.workspace_dir / "auto_memory"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source_memory, destination)
        manifest = json.loads((input_dir / "ingestion_manifest.json").read_text(encoding="utf-8"))
        require(
            manifest.get("experiment_mode", DEFAULT_EXPERIMENT_MODE) == self.experiment_mode,
            "Saved auto-memory experiment mode does not match requested mode",
        )
        saved_version = manifest.get("detected_version")
        require(
            saved_version is None
            or self.detected_version is None
            or saved_version == self.detected_version,
            f"Saved CodeAgent version {saved_version!r} does not match runtime {self.detected_version!r}",
        )
        require(manifest.get("build_status") in {"complete", "complete_with_empty_ingestions", "complete_memory_off"}, f"Saved auto-memory build is not complete: {manifest.get('build_status')}")
        self.inserted_trajectory_ids = list(manifest.get("trajectory_ids", []))
        self.ingestion_records = list(manifest.get("records", []))
        self.ingestion_plan = dict(manifest.get("ingestion_plan", self.ingestion_plan))
        self._write_manifests(status=str(manifest["build_status"]))
