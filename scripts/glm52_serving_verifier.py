# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "zai-org/GLM-5.2"
DEFAULT_RESULTS_DIR = Path("glm52-serving-results")
EXPECTED_FINAL_SCORE = 19
EXPECTED_RISK = "src/alpha.py"
REQUIRED_READS = {"README.md", "src/alpha.py", "src/beta.py"}
TERMINAL_BENCH_PATH = "src/slug.py"
TERMINAL_BENCH_TEST_COMMANDS = {"pytest", "python -m pytest", "uv run pytest"}
TERMINAL_BENCH_FIXED_SOURCE = 'def slugify(value):\n    return value.strip().lower().replace(" ", "-")\n'


class VerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class AgentRun:
    final_text: str
    tool_calls: list[ToolCall]
    turns: list[dict[str, Any]]


@dataclass
class TerminalBenchState:
    files: dict[str, str]

    def __init__(self) -> None:
        self.files = {
            TERMINAL_BENCH_PATH: 'def slugify(value):\n    return value.lower()\n',
            "tests/test_slug.py": (
                "from src.slug import slugify\n\n"
                "def test_slugify_trims_and_replaces_spaces():\n"
                "    assert slugify(' Hello GLM ') == 'hello-glm'\n\n"
                "def test_slugify_keeps_single_words():\n"
                "    assert slugify('Codex') == 'codex'\n"
            ),
        }

    @classmethod
    def from_tool_calls(cls, calls: list[ToolCall]) -> "TerminalBenchState":
        state = cls()
        for call in calls:
            if call.name in {"terminal_run", "terminal_read_file", "terminal_write_file"}:
                execute_terminal_tool(state, call)
        return state


class JsonHttpClient:
    def __init__(
        self,
        *,
        api_key: str | None,
        timeout_seconds: float,
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def get_json(self, url: str) -> Any:
        request = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise VerificationError(_http_error_message(error)) from error
        except urllib.error.URLError as error:
            raise VerificationError(f"request failed: {error}") from error

    def post_json(self, url: str, payload: dict[str, Any]) -> Any:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers=self._headers({"Content-Type": "application/json"}),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise VerificationError(_http_error_message(error)) from error
        except urllib.error.URLError as error:
            raise VerificationError(f"request failed: {error}") from error

    def post_sse(self, url: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers=self._headers({"Content-Type": "application/json", "Accept": "text/event-stream"}),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return list(parse_sse_events(response.read().decode("utf-8")))
        except urllib.error.HTTPError as error:
            raise VerificationError(_http_error_message(error)) from error
        except urllib.error.URLError as error:
            raise VerificationError(f"request failed: {error}") from error

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(extra or {})
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


def _http_error_message(error: urllib.error.HTTPError) -> str:
    body = error.read().decode("utf-8", "replace")
    return f"HTTP {error.code}: {body[:1000]}"


def parse_sse_events(text: str) -> list[dict[str, Any]]:
    events = []
    current_data: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            if current_data:
                event = "\n".join(current_data)
                current_data = []
                if event != "[DONE]":
                    events.append(json.loads(event))
            continue
        if line.startswith("data:"):
            current_data.append(line.removeprefix("data:").strip())

    if current_data:
        event = "\n".join(current_data)
        if event != "[DONE]":
            events.append(json.loads(event))
    return events


def join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def model_list_contains(payload: Any, model: str) -> bool:
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    if not isinstance(data, list):
        return False
    for item in data:
        if isinstance(item, dict) and item.get("id") == model:
            return True
    return False


def virtual_tool_definitions_chat() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "list_project_files",
                "description": "List files in the synthetic project that the verifier asks about.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_project_file",
                "description": "Read one synthetic project file by path.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        },
    ]


def virtual_tool_definitions_responses() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": "list_project_files",
            "description": "List files in the synthetic project that the verifier asks about.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "type": "function",
            "name": "read_project_file",
            "description": "Read one synthetic project file by path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    ]


def terminal_tool_definitions_responses() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": "terminal_run",
            "description": "Run an allowlisted terminal command in the synthetic coding benchmark.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "terminal_read_file",
            "description": "Read one file from the synthetic coding benchmark workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "terminal_write_file",
            "description": "Replace one file in the synthetic coding benchmark workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    ]


def complex_task_prompt() -> str:
    return (
        "Use the tools to inspect the synthetic project. Read the scoring rule and every module data file. "
        "Compute the total release score across modules and identify risky modules. "
        "A module is risky only when the scoring rule says it is risky. "
        "Return exactly two lines: FINAL_SCORE: <integer> and RISKS: <comma-separated paths or none>."
    )


def complex_task_instructions() -> str:
    return (
        "You are a coding-agent verifier. You must use the provided tools instead of guessing. "
        "Do arithmetic carefully. Do not call tools that are not provided."
    )


def terminal_bench_prompt() -> str:
    return (
        "You are in a tiny repository. Use terminal tools to diagnose and fix the failing tests. "
        "You may run pytest, read files, and write src/slug.py. "
        "Finish only after tests pass. Return exactly three lines: TERMINAL_BENCH: PASS, "
        "PATCHED: src/slug.py, and TESTS: <command you ran successfully>."
    )


def terminal_bench_instructions() -> str:
    return (
        "Use the provided terminal tools instead of guessing. Do not claim success until a terminal_run tool "
        "returns exit_code 0 after your edit."
    )


def execute_virtual_tool(call: ToolCall) -> str:
    try:
        args = json.loads(call.arguments or "{}")
    except json.JSONDecodeError as error:
        raise VerificationError(f"tool call {call.name} has invalid JSON arguments: {call.arguments}") from error

    if call.name == "list_project_files":
        return json.dumps(
            {
                "files": [
                    "README.md",
                    "src/alpha.py",
                    "src/beta.py",
                    "docs/notes.md",
                ]
            },
            sort_keys=True,
        )

    if call.name == "read_project_file":
        path = args.get("path")
        files = {
            "README.md": (
                "Scoring rule: per module score = 3 * open_issues + 2 * failing_tests - docs_points + floor(max_latency_ms / 10). "
                "Total release score is the sum of per module scores. "
                "A module is risky when coverage_percent < 80 or todo_count > 1."
            ),
            "src/alpha.py": json.dumps(
                {
                    "module": "src/alpha.py",
                    "open_issues": 4,
                    "failing_tests": 1,
                    "docs_points": 3,
                    "max_latency_ms": 70,
                    "coverage_percent": 78,
                    "todo_count": 2,
                },
                sort_keys=True,
            ),
            "src/beta.py": json.dumps(
                {
                    "module": "src/beta.py",
                    "open_issues": 1,
                    "failing_tests": 0,
                    "docs_points": 4,
                    "max_latency_ms": 20,
                    "coverage_percent": 91,
                    "todo_count": 0,
                },
                sort_keys=True,
            ),
            "docs/notes.md": "Not part of the module score.",
        }
        if path not in files:
            raise VerificationError(f"unknown synthetic project path: {path}")
        return json.dumps({"path": path, "content": files[path]}, sort_keys=True)

    raise VerificationError(f"unknown tool call: {call.name}")


def execute_terminal_tool(state: TerminalBenchState, call: ToolCall) -> str:
    try:
        args = json.loads(call.arguments or "{}")
    except json.JSONDecodeError as error:
        raise VerificationError(f"tool call {call.name} has invalid JSON arguments: {call.arguments}") from error

    if call.name == "terminal_run":
        command = args.get("command")
        if command not in TERMINAL_BENCH_TEST_COMMANDS:
            raise VerificationError(f"terminal command is not allowlisted: {command}")
        return json.dumps(_terminal_pytest_result(state), sort_keys=True)

    if call.name == "terminal_read_file":
        path = args.get("path")
        if not isinstance(path, str) or path not in state.files:
            raise VerificationError(f"unknown terminal bench path: {path}")
        return json.dumps({"path": path, "content": state.files[path]}, sort_keys=True)

    if call.name == "terminal_write_file":
        path = args.get("path")
        content = args.get("content")
        if path != TERMINAL_BENCH_PATH:
            raise VerificationError(f"terminal bench may only write {TERMINAL_BENCH_PATH}")
        if not isinstance(content, str):
            raise VerificationError("terminal_write_file requires string content")
        state.files[path] = content
        return json.dumps({"ok": True, "path": path}, sort_keys=True)

    raise VerificationError(f"unknown terminal bench tool call: {call.name}")


def execute_terminal_tool_output(state: TerminalBenchState, call: ToolCall) -> str:
    try:
        return execute_terminal_tool(state, call)
    except VerificationError as error:
        return json.dumps({"ok": False, "error": str(error)}, sort_keys=True)


def _terminal_pytest_result(state: TerminalBenchState) -> dict[str, Any]:
    source = state.files[TERMINAL_BENCH_PATH]
    if source == TERMINAL_BENCH_FIXED_SOURCE:
        return {
            "command": "python -m pytest",
            "exit_code": 0,
            "stdout": "tests/test_slug.py ..\n2 passed",
            "stderr": "",
        }
    return {
        "command": "python -m pytest",
        "exit_code": 1,
        "stdout": "tests/test_slug.py F.",
        "stderr": "expected slugify(' Hello GLM ') to equal 'hello-glm'",
    }


def validate_complex_task(run: AgentRun) -> None:
    if len(run.tool_calls) < 4:
        raise VerificationError(f"expected at least 4 tool calls, got {len(run.tool_calls)}")

    read_paths = set()
    for call in run.tool_calls:
        if call.name != "read_project_file":
            continue
        try:
            args = json.loads(call.arguments or "{}")
        except json.JSONDecodeError as error:
            raise VerificationError(f"invalid read_project_file arguments: {call.arguments}") from error
        path = args.get("path")
        if isinstance(path, str):
            read_paths.add(path)

    missing = REQUIRED_READS - read_paths
    if missing:
        raise VerificationError(f"model did not read required files: {sorted(missing)}")

    normalized = " ".join(run.final_text.strip().split())
    if f"FINAL_SCORE: {EXPECTED_FINAL_SCORE}" not in normalized:
        raise VerificationError(f"final answer did not contain FINAL_SCORE: {EXPECTED_FINAL_SCORE}: {run.final_text!r}")
    if "RISKS:" not in normalized or EXPECTED_RISK not in normalized:
        raise VerificationError(f"final answer did not identify {EXPECTED_RISK} as risky: {run.final_text!r}")


def validate_terminal_bench(run: AgentRun, state: TerminalBenchState) -> None:
    wrote_slug = False
    test_commands = []
    for call in run.tool_calls:
        try:
            args = json.loads(call.arguments or "{}")
        except json.JSONDecodeError as error:
            raise VerificationError(f"invalid terminal bench arguments: {call.arguments}") from error
        if call.name == "terminal_write_file" and args.get("path") == TERMINAL_BENCH_PATH:
            wrote_slug = True
        if call.name == "terminal_run" and isinstance(args.get("command"), str):
            test_commands.append(args["command"])

    if not wrote_slug:
        raise VerificationError(f"terminal bench did not write {TERMINAL_BENCH_PATH}")
    if not test_commands:
        raise VerificationError("terminal bench did not run tests")
    if _terminal_pytest_result(state)["exit_code"] != 0:
        raise VerificationError(f"terminal bench tests are not passing after tool calls: {state.files[TERMINAL_BENCH_PATH]!r}")

    normalized = " ".join(run.final_text.strip().split())
    if "TERMINAL_BENCH: PASS" not in normalized:
        raise VerificationError(f"final answer did not report TERMINAL_BENCH: PASS: {run.final_text!r}")
    if f"PATCHED: {TERMINAL_BENCH_PATH}" not in normalized:
        raise VerificationError(f"final answer did not report patched file {TERMINAL_BENCH_PATH}: {run.final_text!r}")
    if "TESTS:" not in normalized:
        raise VerificationError(f"final answer did not report test command: {run.final_text!r}")


def extract_chat_tool_calls(message: dict[str, Any]) -> list[ToolCall]:
    calls = []
    for raw_call in message.get("tool_calls") or []:
        function = raw_call.get("function") or {}
        calls.append(
            ToolCall(
                call_id=str(raw_call.get("id") or f"call_{len(calls)}"),
                name=str(function.get("name") or ""),
                arguments=str(function.get("arguments") or "{}"),
            )
        )
    return calls


def extract_chat_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    reasoning = message.get("reasoning_content")
    if isinstance(content, str) and content:
        return content
    if isinstance(reasoning, str) and reasoning:
        return reasoning
    return ""


def _responses_error_message(error_payload: Any) -> str:
    if isinstance(error_payload, dict):
        message = error_payload.get("message")
        if isinstance(message, str) and message:
            return message
        return json.dumps(error_payload, sort_keys=True)
    return str(error_payload)


def run_chat_health(
    client: JsonHttpClient,
    *,
    base_url: str,
    model: str,
    max_tokens: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: GLM52_HEALTH_OK"}],
        "max_tokens": max_tokens,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    response = client.post_json(join_url(base_url, "/chat/completions"), payload)
    choices = response.get("choices") if isinstance(response, dict) else None
    if not choices:
        raise VerificationError("chat health response has no choices")
    message = choices[0].get("message") or {}
    text = extract_chat_text(message)
    if "GLM52_HEALTH_OK" not in text:
        raise VerificationError(f"chat health response did not contain GLM52_HEALTH_OK: {text!r}")
    return {"ok": True, "text": text, "raw": response}


def run_chat_agent(
    client: JsonHttpClient,
    *,
    base_url: str,
    model: str,
    max_tokens: int,
    max_turns: int,
) -> AgentRun:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": complex_task_instructions()},
        {"role": "user", "content": complex_task_prompt()},
    ]
    tool_calls: list[ToolCall] = []
    turns: list[dict[str, Any]] = []

    for _turn in range(max_turns):
        payload = {
            "model": model,
            "messages": messages,
            "tools": virtual_tool_definitions_chat(),
            "tool_choice": "auto",
            "max_tokens": max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        response = client.post_json(join_url(base_url, "/chat/completions"), payload)
        choices = response.get("choices") if isinstance(response, dict) else None
        if not choices:
            raise VerificationError("chat agent response has no choices")
        message = choices[0].get("message") or {}
        calls = extract_chat_tool_calls(message)
        turns.append({"assistant": message})

        if not calls:
            final_text = extract_chat_text(message)
            run = AgentRun(final_text=final_text, tool_calls=tool_calls, turns=turns)
            validate_complex_task(run)
            return run

        messages.append(message)
        for call in calls:
            tool_calls.append(call)
            output = execute_virtual_tool(call)
            turns.append({"tool_call": call.__dict__, "tool_output": output})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.call_id,
                    "name": call.name,
                    "content": output,
                }
            )

    raise VerificationError(f"chat agent did not finish within {max_turns} turns")


def parse_responses_nonstream(payload: dict[str, Any]) -> tuple[str | None, str, list[ToolCall]]:
    if payload.get("error") is not None:
        raise VerificationError(f"Responses API error: {_responses_error_message(payload['error'])}")

    response_id = payload.get("id") if isinstance(payload.get("id"), str) else None
    text_parts: list[str] = []
    calls: list[ToolCall] = []

    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type in {"function_call", "function_call_output"} and item.get("name"):
                calls.append(
                    ToolCall(
                        call_id=str(item.get("call_id") or item.get("id") or f"call_{len(calls)}"),
                        name=str(item.get("name")),
                        arguments=str(item.get("arguments") or "{}"),
                    )
                )
            if item_type == "message":
                for content in item.get("content") or []:
                    if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                        text = content.get("text")
                        if isinstance(text, str):
                            text_parts.append(text)
            if item_type in {"output_text", "text"} and isinstance(item.get("text"), str):
                text_parts.append(item["text"])

    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        text_parts.append(output_text)
    return response_id, "".join(text_parts), calls


def parse_responses_stream(events: list[dict[str, Any]]) -> tuple[str | None, str, list[ToolCall]]:
    response_id: str | None = None
    text_parts: list[str] = []
    calls_by_item: dict[str, dict[str, str]] = {}
    item_order: list[str] = []

    for event in events:
        event_type = event.get("type")
        if event_type == "error" and event.get("error") is not None:
            raise VerificationError(f"Responses stream error: {_responses_error_message(event['error'])}")
        response = event.get("response")
        if isinstance(response, dict) and isinstance(response.get("id"), str):
            response_id = response["id"]
        if event_type == "response.output_text.delta" and isinstance(event.get("delta"), str):
            text_parts.append(event["delta"])
        if event_type in {"response.output_item.added", "response.output_item.done"}:
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "function_call":
                item_id = str(item.get("id") or item.get("call_id") or f"item_{len(item_order)}")
                if item_id not in calls_by_item:
                    item_order.append(item_id)
                    calls_by_item[item_id] = {
                        "call_id": str(item.get("call_id") or item_id),
                        "name": str(item.get("name") or ""),
                        "arguments": "",
                    }
                if item.get("name"):
                    calls_by_item[item_id]["name"] = str(item["name"])
                if item.get("arguments"):
                    calls_by_item[item_id]["arguments"] = str(item["arguments"])
        if event_type == "response.function_call_arguments.delta":
            item_id = _responses_event_item_id(event, item_order)
            if item_id is not None:
                calls_by_item[item_id]["arguments"] += str(event.get("delta") or "")
        if event_type == "response.function_call_arguments.done":
            item_id = _responses_event_item_id(event, item_order)
            if item_id is not None and event.get("arguments") is not None:
                calls_by_item[item_id]["arguments"] = str(event["arguments"])

    completed = [event.get("response") for event in events if event.get("type") == "response.completed" and isinstance(event.get("response"), dict)]
    for response in completed:
        parsed_id, parsed_text, parsed_calls = parse_responses_nonstream(response)
        response_id = response_id or parsed_id
        if parsed_text and not text_parts:
            text_parts.append(parsed_text)
        for call in parsed_calls:
            if call.call_id not in {data["call_id"] for data in calls_by_item.values()}:
                item_id = f"completed_{len(item_order)}"
                item_order.append(item_id)
                calls_by_item[item_id] = call.__dict__

    calls = [
        ToolCall(
            call_id=calls_by_item[item_id]["call_id"],
            name=calls_by_item[item_id]["name"],
            arguments=calls_by_item[item_id]["arguments"] or "{}",
        )
        for item_id in item_order
    ]
    return response_id, "".join(text_parts), calls


def _responses_event_item_id(event: dict[str, Any], item_order: list[str]) -> str | None:
    for key in ("item_id", "output_item_id"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    index = event.get("output_index")
    if isinstance(index, int) and 0 <= index < len(item_order):
        return item_order[index]
    if len(item_order) == 1:
        return item_order[0]
    return None


def run_responses_agent(
    client: JsonHttpClient,
    *,
    base_url: str,
    model: str,
    max_tokens: int,
    max_turns: int,
    stream: bool,
) -> AgentRun:
    previous_response_id: str | None = None
    next_input: str | list[dict[str, Any]] = complex_task_prompt()
    tool_calls: list[ToolCall] = []
    turns: list[dict[str, Any]] = []

    for _turn in range(max_turns):
        payload: dict[str, Any] = {
            "model": model,
            "instructions": complex_task_instructions(),
            "input": next_input,
            "tools": virtual_tool_definitions_responses(),
            "tool_choice": "auto",
            "max_output_tokens": max_tokens,
            "stream": stream,
        }
        if previous_response_id is not None:
            payload["previous_response_id"] = previous_response_id

        if stream:
            events = client.post_sse(join_url(base_url, "/responses"), payload)
            response_id, text, calls = parse_responses_stream(events)
            turns.append({"events": events})
        else:
            response = client.post_json(join_url(base_url, "/responses"), payload)
            response_id, text, calls = parse_responses_nonstream(response)
            turns.append({"response": response})

        previous_response_id = response_id or previous_response_id
        if not calls:
            run = AgentRun(final_text=text, tool_calls=tool_calls, turns=turns)
            validate_complex_task(run)
            return run

        outputs = []
        for call in calls:
            tool_calls.append(call)
            output = execute_virtual_tool(call)
            turns.append({"tool_call": call.__dict__, "tool_output": output})
            outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": output})
        next_input = outputs

    raise VerificationError(f"responses agent did not finish within {max_turns} turns")


def run_terminal_bench_responses(
    client: JsonHttpClient,
    *,
    base_url: str,
    model: str,
    max_tokens: int,
    max_turns: int,
    stream: bool,
) -> AgentRun:
    previous_response_id: str | None = None
    next_input: str | list[dict[str, Any]] = terminal_bench_prompt()
    tool_calls: list[ToolCall] = []
    turns: list[dict[str, Any]] = []
    state = TerminalBenchState()

    for _turn in range(max_turns):
        payload: dict[str, Any] = {
            "model": model,
            "instructions": terminal_bench_instructions(),
            "input": next_input,
            "tools": terminal_tool_definitions_responses(),
            "tool_choice": "auto",
            "max_output_tokens": max_tokens,
            "stream": stream,
        }
        if previous_response_id is not None:
            payload["previous_response_id"] = previous_response_id

        if stream:
            events = client.post_sse(join_url(base_url, "/responses"), payload)
            response_id, text, calls = parse_responses_stream(events)
            turns.append({"events": events})
        else:
            response = client.post_json(join_url(base_url, "/responses"), payload)
            response_id, text, calls = parse_responses_nonstream(response)
            turns.append({"response": response})

        previous_response_id = response_id or previous_response_id
        if not calls:
            run = AgentRun(final_text=text, tool_calls=tool_calls, turns=turns)
            validate_terminal_bench(run, state)
            return run

        outputs = []
        for call in calls:
            tool_calls.append(call)
            output = execute_terminal_tool_output(state, call)
            turns.append({"tool_call": call.__dict__, "tool_output": output})
            outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": output})
        next_input = outputs

    raise VerificationError(f"terminal bench did not finish within {max_turns} turns")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_serving_archive_manifest(
    *,
    results_dir: Path,
    summary: dict[str, Any],
) -> Path:
    artifact_files = sorted(
        (
            path
            for path in results_dir.rglob("*")
            if path.is_file() and path.name != "archive-manifest.json"
        ),
        key=lambda path: str(path.relative_to(results_dir)),
    )
    artifacts = [str(path.relative_to(results_dir)) for path in artifact_files]
    artifact_hashes = {
        str(path.relative_to(results_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in artifact_files
    }
    path = results_dir / "archive-manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "summary_status": summary["status"],
                "summary_path": "summary.json",
                "terminal": summary["status"] != "running",
                "contract_artifacts": artifacts,
                "contract_artifact_sha256": artifact_hashes,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return path


def agent_run_json(run: AgentRun) -> dict[str, Any]:
    return {
        "final_text": run.final_text,
        "tool_calls": [call.__dict__ for call in run.tool_calls],
        "turns": run.turns,
    }


def run_stage(
    summary: list[dict[str, Any]],
    *,
    name: str,
    results_dir: Path,
    keep_going: bool,
    func,
) -> bool:
    start = time.monotonic()
    try:
        artifact = func()
    except Exception as error:
        entry = {"stage": name, "status": "fail", "error": str(error), "seconds": round(time.monotonic() - start, 3)}
        summary.append(entry)
        write_json(results_dir / f"{name}.json", entry)
        print(f"{name}: FAIL: {error}", file=sys.stderr)
        if not keep_going:
            raise
        return False

    entry = {"stage": name, "status": "pass", "seconds": round(time.monotonic() - start, 3)}
    summary.append(entry)
    write_json(results_dir / f"{name}.json", {"result": artifact, **entry})
    print(f"{name}: PASS")
    return True


def run_optional_stage(
    summary: list[dict[str, Any]],
    *,
    name: str,
    results_dir: Path,
    func,
) -> None:
    start = time.monotonic()
    try:
        artifact = func()
    except Exception as error:
        entry = {
            "stage": name,
            "status": "warning",
            "error": str(error),
            "seconds": round(time.monotonic() - start, 3),
        }
        summary.append(entry)
        write_json(results_dir / f"{name}.json", entry)
        print(f"{name}: WARNING: {error}", file=sys.stderr)
        return

    entry = {
        "stage": name,
        "status": "pass",
        "seconds": round(time.monotonic() - start, 3),
    }
    summary.append(entry)
    write_json(results_dir / f"{name}.json", {"result": artifact, **entry})
    print(f"{name}: PASS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify a local GLM-5.2 Dynamo/SGLang deployment and Responses adapter.")
    parser.add_argument("--model", default=os.environ.get("GLM52_MODEL", DEFAULT_MODEL))
    parser.add_argument("--chat-base-url", default=os.environ.get("GLM52_CHAT_BASE_URL"))
    parser.add_argument("--responses-base-url", default=os.environ.get("GLM52_RESPONSES_BASE_URL"))
    parser.add_argument("--api-key-env", default=os.environ.get("GLM52_API_KEY_ENV", "GLM_API_KEY"))
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--skip-chat", action="store_true")
    parser.add_argument("--skip-responses", action="store_true")
    parser.add_argument("--terminal-bench", action="store_true")
    parser.add_argument("--responses-non-stream", action="store_true")
    parser.add_argument("--keep-going", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.results_dir.mkdir(parents=True, exist_ok=True)
    api_key = os.environ.get(args.api_key_env) or None
    client = JsonHttpClient(api_key=api_key, timeout_seconds=args.timeout_seconds)
    summary: list[dict[str, Any]] = []

    def environment() -> dict[str, Any]:
        if args.skip_chat and args.skip_responses:
            raise VerificationError("at least one of chat or responses verification must run")
        if not args.skip_chat and not args.chat_base_url:
            raise VerificationError("set --chat-base-url or GLM52_CHAT_BASE_URL, or pass --skip-chat")
        if not args.skip_responses and not args.responses_base_url:
            raise VerificationError("set --responses-base-url or GLM52_RESPONSES_BASE_URL, or pass --skip-responses")
        return {
            "model": args.model,
            "chat_base_url": args.chat_base_url,
            "responses_base_url": args.responses_base_url,
            "api_key_env": args.api_key_env,
            "api_key_present": api_key is not None,
            "results_dir": str(args.results_dir),
            "timeout_seconds": args.timeout_seconds,
            "max_tokens": args.max_tokens,
            "max_turns": args.max_turns,
            "keep_going": args.keep_going,
            "terminal_bench": args.terminal_bench,
            "responses_stream": not args.responses_non_stream,
            "responses_non_stream": args.responses_non_stream,
        }

    try:
        run_stage(summary, name="environment", results_dir=args.results_dir, keep_going=args.keep_going, func=environment)

        if not args.skip_chat:
            assert args.chat_base_url is not None

            def chat_models() -> dict[str, Any]:
                payload = client.get_json(join_url(args.chat_base_url, "/models"))
                contains_model = model_list_contains(payload, args.model)
                if not contains_model:
                    raise VerificationError(f"/models did not advertise {args.model}")
                return {"contains_model": contains_model, "raw": payload}

            run_optional_stage(
                summary,
                name="chat-models",
                results_dir=args.results_dir,
                func=chat_models,
            )
            run_stage(
                summary,
                name="chat-health",
                results_dir=args.results_dir,
                keep_going=args.keep_going,
                func=lambda: run_chat_health(client, base_url=args.chat_base_url, model=args.model, max_tokens=args.max_tokens),
            )
            run_stage(
                summary,
                name="chat-agent",
                results_dir=args.results_dir,
                keep_going=args.keep_going,
                func=lambda: agent_run_json(
                    run_chat_agent(
                        client,
                        base_url=args.chat_base_url,
                        model=args.model,
                        max_tokens=args.max_tokens,
                        max_turns=args.max_turns,
                    )
                ),
            )

        if not args.skip_responses:
            assert args.responses_base_url is not None

            def responses_models() -> dict[str, Any]:
                payload = client.get_json(join_url(args.responses_base_url, "/models"))
                contains_model = model_list_contains(payload, args.model)
                if not contains_model:
                    raise VerificationError(f"/models did not advertise {args.model}")
                return {"contains_model": contains_model, "raw": payload}

            run_stage(summary, name="responses-models", results_dir=args.results_dir, keep_going=args.keep_going, func=responses_models)
            run_stage(
                summary,
                name="responses-agent",
                results_dir=args.results_dir,
                keep_going=args.keep_going,
                func=lambda: agent_run_json(
                    run_responses_agent(
                        client,
                        base_url=args.responses_base_url,
                        model=args.model,
                        max_tokens=args.max_tokens,
                        max_turns=args.max_turns,
                        stream=not args.responses_non_stream,
                    )
                ),
            )
            if args.terminal_bench:
                run_stage(
                    summary,
                    name="responses-terminal-bench",
                    results_dir=args.results_dir,
                    keep_going=args.keep_going,
                    func=lambda: agent_run_json(
                        run_terminal_bench_responses(
                            client,
                            base_url=args.responses_base_url,
                            model=args.model,
                            max_tokens=args.max_tokens,
                            max_turns=args.max_turns,
                            stream=not args.responses_non_stream,
                        )
                    ),
                )

    except Exception:
        failed_summary = {"status": "fail", "stages": summary}
        write_json(args.results_dir / "summary.json", failed_summary)
        write_serving_archive_manifest(results_dir=args.results_dir, summary=failed_summary)
        return 1

    status = (
        "pass"
        if all(entry["status"] in {"pass", "warning"} for entry in summary)
        else "fail"
    )
    final_summary = {"status": status, "stages": summary}
    write_json(args.results_dir / "summary.json", final_summary)
    write_serving_archive_manifest(results_dir=args.results_dir, summary=final_summary)
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
