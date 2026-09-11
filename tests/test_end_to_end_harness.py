import argparse
import asyncio
from unittest.mock import patch

from evaluation.harness import build_prompt_row, generate_all_reader_outputs
from memory_modules.memory import AgentAnswer, Memory, MemoryContextItem


class DirectAnswerMemory(Memory):
    memory_type = "test_direct_answer"

    def __init__(self) -> None:
        super().__init__({})
        self.answer_calls: list[tuple[str, str | None]] = []

    def insert(self, trajectory: dict[str, object]) -> None:
        return None

    def query(
        self,
        query: str,
        query_image: str | None = None,
    ) -> list[MemoryContextItem]:
        raise AssertionError("The retrieval path must not run for a direct-answer backend")

    def answer(
        self,
        question: str,
        question_image: str | None = None,
    ) -> AgentAnswer:
        self.answer_calls.append((question, question_image))
        return {
            "response_raw": "Reasoning omitted. \\boxed{Login as Customer}",
            "usage": {"input_tokens": 12, "output_tokens": 3},
            "duration_seconds": 0.25,
            "metadata": {
                "experiment_mode": "candidate",
                "main_memory_unchanged": True,
            },
        }


def _item() -> dict[str, object]:
    return {
        "index": 0,
        "stream_index": 0,
        "question_id": "05cce9b3",
        "query_invocation_id": "05cce9b3/run-1",
        "question_type": "static-environment",
        "category": "static",
        "question_text": "What action is between Delete Customer and Back?",
        "question_image": None,
        "answer_gold": "Login as Customer",
        "eval_name": "norm_phrase_set_match",
        "eval_function": "norm_phrase_set_match",
    }


def test_build_prompt_row_uses_direct_answer_capability() -> None:
    memory = DirectAnswerMemory()
    row = build_prompt_row(
        _item(),
        haystack_ids=["trajectory-one"],
        memory=memory,
        system_prompt="unused external reader prompt",
        memory_context_max_tokens=100,
    )

    assert memory.answer_calls == [
        ("What action is between Delete Customer and Back?", None)
    ]
    assert row["execution_path"] == "end_to_end_agent"
    assert row["experiment_mode"] == "candidate"
    assert row["messages"] == []
    assert row["prompt_messages"] == []
    assert row["memory_context"] == []
    assert row["direct_answer"]["response_raw"].endswith(
        "\\boxed{Login as Customer}"
    )


def test_direct_answer_output_skips_external_reader() -> None:
    memory = DirectAnswerMemory()
    row = build_prompt_row(
        _item(),
        haystack_ids=["trajectory-one"],
        memory=memory,
        system_prompt="unused external reader prompt",
        memory_context_max_tokens=100,
    )
    args = argparse.Namespace(reader_max_concurrent_requests=1)

    with patch(
        "evaluation.harness.create_async_client",
        side_effect=AssertionError("external reader must not be created"),
    ):
        outputs = asyncio.run(generate_all_reader_outputs(args, [row]))

    output = outputs["05cce9b3"]
    assert output["response_parsed_boxed"] == "Login as Customer"
    assert output["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "total_tokens": 15,
    }
