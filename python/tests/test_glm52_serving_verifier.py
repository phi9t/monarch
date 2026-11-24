# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import importlib.util
import hashlib
import json
import sys
from pathlib import Path

import pytest

HELPER_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "glm52_serving_verifier.py"
)
spec = importlib.util.spec_from_file_location("glm52_serving_verifier", HELPER_PATH)
assert spec is not None
assert spec.loader is not None
glm52_serving_verifier = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = glm52_serving_verifier
spec.loader.exec_module(glm52_serving_verifier)

AgentRun = glm52_serving_verifier.AgentRun
TerminalBenchState = glm52_serving_verifier.TerminalBenchState
ToolCall = glm52_serving_verifier.ToolCall
VerificationError = glm52_serving_verifier.VerificationError
execute_virtual_tool = glm52_serving_verifier.execute_virtual_tool
execute_terminal_tool = glm52_serving_verifier.execute_terminal_tool
execute_terminal_tool_output = glm52_serving_verifier.execute_terminal_tool_output
extract_chat_tool_calls = glm52_serving_verifier.extract_chat_tool_calls
parse_responses_nonstream = glm52_serving_verifier.parse_responses_nonstream
parse_responses_stream = glm52_serving_verifier.parse_responses_stream
parse_sse_events = glm52_serving_verifier.parse_sse_events
run_optional_stage = glm52_serving_verifier.run_optional_stage
validate_complex_task = glm52_serving_verifier.validate_complex_task
validate_terminal_bench = glm52_serving_verifier.validate_terminal_bench
write_serving_archive_manifest = glm52_serving_verifier.write_serving_archive_manifest
build_parser = glm52_serving_verifier.build_parser
main = glm52_serving_verifier.main


def test_parse_sse_events_ignores_done() -> None:
    events = parse_sse_events(
        """\
event: response.created
data: {"type": "response.created", "response": {"id": "resp_1"}}

data: {"type": "response.output_text.delta", "delta": "hello"}

data: [DONE]

"""
    )

    assert events == [
        {"type": "response.created", "response": {"id": "resp_1"}},
        {"type": "response.output_text.delta", "delta": "hello"},
    ]


def test_parse_responses_stream_reconstructs_function_call() -> None:
    response_id, text, calls = parse_responses_stream(
        [
            {"type": "response.created", "response": {"id": "resp_1"}},
            {
                "type": "response.output_item.added",
                "item": {
                    "id": "item_1",
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "read_project_file",
                },
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "item_1",
                "delta": "{\"path\": ",
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "item_1",
                "delta": "\"README.md\"}",
            },
            {"type": "response.output_text.delta", "delta": "ignored until final"},
        ]
    )

    assert response_id == "resp_1"
    assert text == "ignored until final"
    assert calls == [
        ToolCall(
            call_id="call_1",
            name="read_project_file",
            arguments='{"path": "README.md"}',
        )
    ]


def test_parse_responses_stream_does_not_duplicate_completed_text() -> None:
    response_id, text, calls = parse_responses_stream(
        [
            {"type": "response.created", "response": {"id": "resp_1"}},
            {"type": "response.output_text.delta", "delta": "FINAL_SCORE: 19"},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_1",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": "FINAL_SCORE: 19"}
                            ],
                        }
                    ],
                },
            },
        ]
    )

    assert response_id == "resp_1"
    assert text == "FINAL_SCORE: 19"
    assert calls == []


def test_parse_responses_stream_rejects_error_event() -> None:
    with pytest.raises(
        VerificationError,
        match="Responses stream error.*downstream Chat Completions stream failed",
    ):
        parse_responses_stream(
            [
                {
                    "type": "error",
                    "error": {
                        "message": "downstream Chat Completions stream failed: upstream closed early"
                    },
                }
            ]
        )


def test_parse_responses_nonstream_extracts_text_and_calls() -> None:
    response_id, text, calls = parse_responses_nonstream(
        {
            "id": "resp_2",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_2",
                    "name": "list_project_files",
                    "arguments": "{}",
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "FINAL_SCORE: 19\nRISKS: src/alpha.py",
                        }
                    ],
                },
            ],
        }
    )

    assert response_id == "resp_2"
    assert text == "FINAL_SCORE: 19\nRISKS: src/alpha.py"
    assert calls == [
        ToolCall(call_id="call_2", name="list_project_files", arguments="{}")
    ]


def test_parse_responses_nonstream_rejects_api_error() -> None:
    with pytest.raises(
        VerificationError,
        match="Responses API error.*downstream Chat Completions error HTTP 404",
    ):
        parse_responses_nonstream(
            {
                "error": {
                    "message": "downstream Chat Completions error HTTP 404: model not found"
                }
            }
        )


def test_extract_chat_tool_calls() -> None:
    calls = extract_chat_tool_calls(
        {
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "read_project_file",
                        "arguments": "{\"path\": \"src/alpha.py\"}",
                    },
                }
            ]
        }
    )

    assert calls == [
        ToolCall(
            call_id="call_1",
            name="read_project_file",
            arguments='{"path": "src/alpha.py"}',
        )
    ]


def test_execute_virtual_tool_returns_project_data() -> None:
    output = execute_virtual_tool(
        ToolCall(
            call_id="call_1",
            name="read_project_file",
            arguments='{"path": "src/alpha.py"}',
        )
    )

    assert "coverage_percent" in output
    assert "src/alpha.py" in output


def test_execute_terminal_tool_runs_tests_edits_file_and_reports_green() -> None:
    state = TerminalBenchState()

    first_test = execute_terminal_tool(
        state,
        ToolCall("call_1", "terminal_run", '{"command": "python -m pytest"}'),
    )
    assert '"exit_code": 1' in first_test
    assert "expected slugify" in first_test

    read_file = execute_terminal_tool(
        state,
        ToolCall("call_2", "terminal_read_file", '{"path": "src/slug.py"}'),
    )
    assert "return value.lower()" in read_file

    edit_file = execute_terminal_tool(
        state,
        ToolCall(
            "call_3",
            "terminal_write_file",
            '{"path": "src/slug.py", "content": "def slugify(value):\\n    return value.strip().lower().replace(\\" \\", \\"-\\")\\n"}',
        ),
    )
    assert '"ok": true' in edit_file

    second_test = execute_terminal_tool(
        state,
        ToolCall("call_4", "terminal_run", '{"command": "python -m pytest"}'),
    )
    assert '"exit_code": 0' in second_test
    assert "2 passed" in second_test


def test_execute_terminal_tool_output_returns_conversation_error() -> None:
    state = TerminalBenchState()

    output = execute_terminal_tool_output(
        state,
        ToolCall("call_1", "terminal_run", '{"command": "rm -rf /"}'),
    )

    assert '"ok": false' in output
    assert "terminal command is not allowlisted" in output
    assert state.files["src/slug.py"] == 'def slugify(value):\n    return value.lower()\n'


def test_validate_terminal_bench_accepts_terminal_fix_run() -> None:
    run = AgentRun(
        final_text="TERMINAL_BENCH: PASS\nPATCHED: src/slug.py\nTESTS: python -m pytest",
        tool_calls=[
            ToolCall("call_1", "terminal_run", '{"command": "python -m pytest"}'),
            ToolCall("call_2", "terminal_read_file", '{"path": "src/slug.py"}'),
            ToolCall(
                "call_3",
                "terminal_write_file",
                '{"path": "src/slug.py", "content": "def slugify(value):\\n    return value.strip().lower().replace(\\" \\", \\"-\\")\\n"}',
            ),
            ToolCall("call_4", "terminal_run", '{"command": "python -m pytest"}'),
        ],
        turns=[],
    )

    validate_terminal_bench(run, TerminalBenchState.from_tool_calls(run.tool_calls))


def test_validate_terminal_bench_rejects_no_edit() -> None:
    run = AgentRun(
        final_text="TERMINAL_BENCH: PASS\nPATCHED: src/slug.py\nTESTS: python -m pytest",
        tool_calls=[
            ToolCall("call_1", "terminal_run", '{"command": "python -m pytest"}'),
            ToolCall("call_2", "terminal_read_file", '{"path": "src/slug.py"}'),
            ToolCall("call_3", "terminal_run", '{"command": "python -m pytest"}'),
        ],
        turns=[],
    )

    with pytest.raises(VerificationError, match="did not write src/slug.py"):
        validate_terminal_bench(run, TerminalBenchState.from_tool_calls(run.tool_calls))


def test_validate_complex_task_accepts_required_reads_and_answer() -> None:
    run = AgentRun(
        final_text="FINAL_SCORE: 19\nRISKS: src/alpha.py",
        tool_calls=[
            ToolCall("call_1", "list_project_files", "{}"),
            ToolCall("call_2", "read_project_file", '{"path": "README.md"}'),
            ToolCall("call_3", "read_project_file", '{"path": "src/alpha.py"}'),
            ToolCall("call_4", "read_project_file", '{"path": "src/beta.py"}'),
        ],
        turns=[],
    )

    validate_complex_task(run)


def test_validate_complex_task_rejects_missing_required_file() -> None:
    run = AgentRun(
        final_text="FINAL_SCORE: 19\nRISKS: src/alpha.py",
        tool_calls=[
            ToolCall("call_1", "list_project_files", "{}"),
            ToolCall("call_2", "read_project_file", '{"path": "README.md"}'),
            ToolCall("call_3", "read_project_file", '{"path": "src/alpha.py"}'),
            ToolCall("call_4", "read_project_file", '{"path": "docs/notes.md"}'),
        ],
        turns=[],
    )

    with pytest.raises(VerificationError, match="did not read required files"):
        validate_complex_task(run)


def test_validate_complex_task_rejects_wrong_score() -> None:
    run = AgentRun(
        final_text="FINAL_SCORE: 20\nRISKS: src/alpha.py",
        tool_calls=[
            ToolCall("call_1", "list_project_files", "{}"),
            ToolCall("call_2", "read_project_file", '{"path": "README.md"}'),
            ToolCall("call_3", "read_project_file", '{"path": "src/alpha.py"}'),
            ToolCall("call_4", "read_project_file", '{"path": "src/beta.py"}'),
        ],
        turns=[],
    )

    with pytest.raises(VerificationError, match="FINAL_SCORE: 19"):
        validate_complex_task(run)


def test_optional_stage_records_warning_without_failure(tmp_path: Path) -> None:
    summary = []

    run_optional_stage(
        summary,
        name="chat-models",
        results_dir=tmp_path,
        func=lambda: (_ for _ in ()).throw(VerificationError("missing /models")),
    )

    assert len(summary) == 1
    assert summary[0]["stage"] == "chat-models"
    assert summary[0]["status"] == "warning"
    assert summary[0]["error"] == "missing /models"
    assert isinstance(summary[0]["seconds"], float)
    assert '"status": "warning"' in (tmp_path / "chat-models.json").read_text()


def test_build_parser_reads_documented_api_key_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GLM52_API_KEY_ENV", "GLM_TEST_API_KEY")

    args = build_parser().parse_args(["--skip-chat", "--skip-responses"])

    assert args.api_key_env == "GLM_TEST_API_KEY"


def test_environment_artifact_records_run_mode_knobs(tmp_path: Path) -> None:
    result = main(
        [
            "--skip-chat",
            "--responses-base-url",
            "http://127.0.0.1:9/v1",
            "--results-dir",
            str(tmp_path),
            "--timeout-seconds",
            "0.01",
            "--max-tokens",
            "77",
            "--max-turns",
            "3",
            "--keep-going",
            "--terminal-bench",
            "--responses-non-stream",
        ]
    )

    assert result == 1
    environment = json.loads((tmp_path / "environment.json").read_text())
    assert environment["status"] == "pass"
    assert environment["result"] == {
        "model": "zai-org/GLM-5.2",
        "chat_base_url": None,
        "responses_base_url": "http://127.0.0.1:9/v1",
        "api_key_env": "GLM_API_KEY",
        "api_key_present": False,
        "results_dir": str(tmp_path),
        "timeout_seconds": 0.01,
        "max_tokens": 77,
        "max_turns": 3,
        "keep_going": True,
        "terminal_bench": True,
        "responses_stream": False,
        "responses_non_stream": True,
    }


def test_write_serving_archive_manifest_records_relative_contract_artifacts(
    tmp_path: Path,
) -> None:
    environment_payload = '{"stage": "environment"}\n'
    responses_payload = '{"stage": "responses-agent"}\n'
    summary_payload = '{"status": "pass"}\n'
    (tmp_path / "environment.json").write_text('{"stage": "environment"}\n')
    (tmp_path / "responses-agent.json").write_text('{"stage": "responses-agent"}\n')
    (tmp_path / "summary.json").write_text('{"status": "pass"}\n')

    path = write_serving_archive_manifest(
        results_dir=tmp_path,
        summary={"status": "pass", "stages": []},
    )

    archive_manifest = json.loads(path.read_text())
    assert archive_manifest == {
        "schema_version": 1,
        "summary_status": "pass",
        "summary_path": "summary.json",
        "terminal": True,
        "contract_artifacts": [
            "environment.json",
            "responses-agent.json",
            "summary.json",
        ],
        "contract_artifact_sha256": {
            "environment.json": hashlib.sha256(environment_payload.encode()).hexdigest(),
            "responses-agent.json": hashlib.sha256(responses_payload.encode()).hexdigest(),
            "summary.json": hashlib.sha256(summary_payload.encode()).hexdigest(),
        },
    }
