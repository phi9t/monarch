#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request as urllib_request


AGENT_VERSION = "glm52-harbor-agent-v1"


class HarborAgentError(RuntimeError):
    pass


@dataclass(frozen=True)
class _FallbackModelInfo:
    name: str
    provider: str | None = None


@dataclass(frozen=True)
class _FallbackAgentInfo:
    name: str
    version: str
    model_info: Any | None = None


@dataclass(init=False)
class GLM52HarborAgent:
    responses_base_url: str
    model: str = "zai-org/GLM-5.2"
    local_host_route: str = "host.docker.internal"
    stream: bool = True
    extra_env: dict[str, str]
    logs_dir: Path | None = None

    def __init__(
        self,
        *,
        responses_base_url: str,
        model: str | None = None,
        model_name: str | None = None,
        local_host_route: str = "host.docker.internal",
        stream: bool = True,
        logs_dir: Path | str | None = None,
        **_kwargs: Any,
    ) -> None:
        selected_model = (
            model
            if model is not None
            else model_name
            if model_name is not None
            else "zai-org/GLM-5.2"
        )
        object.__setattr__(self, "responses_base_url", responses_base_url)
        object.__setattr__(self, "model", selected_model)
        object.__setattr__(self, "local_host_route", local_host_route)
        object.__setattr__(self, "stream", stream)
        object.__setattr__(self, "extra_env", {})
        object.__setattr__(self, "logs_dir", None if logs_dir is None else Path(logs_dir))

    @staticmethod
    def name() -> str:
        return "glm52-responses"

    def version(self) -> str:
        return AGENT_VERSION

    @classmethod
    def import_path(cls) -> str:
        return f"{cls.__module__}:{cls.__name__}"

    async def setup(self, *, environment: Any) -> None:
        return None

    async def run(self, instruction: str, environment: Any, context: Any) -> None:
        tools = [_terminal_tool()]
        response = await _post_responses_request(
            self,
            self.build_responses_request(
                task_instruction=instruction,
                observation="No prior observation.",
                tools=tools,
            ),
        )

        for _ in range(16):
            function_calls = [
                item
                for item in response.get("output", [])
                if item.get("type") == "function_call"
            ]
            if not function_calls:
                _populate_context_from_response(context, response)
                return

            outputs = []
            for item in function_calls:
                outputs.append(
                    await _execute_function_call(
                        item,
                        environment=environment,
                    )
                )

            response_id = response.get("id")
            if not isinstance(response_id, str) or not response_id:
                raise HarborAgentError("response with function_call requires id")
            response = await _post_responses_request(
                self,
                {
                    "model": self.model,
                    "input": outputs,
                    "previous_response_id": response_id,
                    "tools": [_harbor_tool_to_responses_tool(tool) for tool in tools],
                    "tool_choice": "auto",
                    "stream": self.stream,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )

        raise HarborAgentError("responses tool loop exceeded maximum iterations")

    def populate_context_post_run(self, context: Any) -> None:
        return None

    def to_agent_info(self) -> Any:
        model_provider, model_name = _parse_model_provider_name(self.model)
        agent_info_cls, model_info_cls = _harbor_agent_info_types()
        return agent_info_cls(
            name=self.name(),
            version=self.version(),
            model_info=model_info_cls(
                name=model_name,
                provider=model_provider,
            ),
        )

    def build_responses_request(
        self,
        *,
        task_instruction: str,
        observation: str,
        tools: list[dict[str, Any]],
        previous_response_id: str | None = None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": (
                "You are running a terminal benchmark task through Harbor. "
                "Use the available tools to inspect, edit, test, and then answer."
            ),
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                f"TASK:\n{task_instruction}\n\n"
                                f"OBSERVATION:\n{observation}"
                            ),
                        }
                    ],
                }
            ],
            "tools": [_harbor_tool_to_responses_tool(tool) for tool in tools],
            "tool_choice": "auto",
            "stream": self.stream,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if previous_response_id is not None:
            request["previous_response_id"] = previous_response_id
        return request


def _harbor_agent_info_types() -> tuple[type[Any], type[Any]]:
    try:
        from harbor.models.trial.result import AgentInfo, ModelInfo
    except ImportError:
        return _FallbackAgentInfo, _FallbackModelInfo
    return AgentInfo, ModelInfo


def _terminal_tool() -> dict[str, Any]:
    return {
        "name": "terminal_run",
        "description": "Run a terminal command in the Harbor environment.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "env": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "timeout_sec": {"type": "integer"},
                "user": {"type": ["string", "integer"]},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    }


def _parse_model_provider_name(model: str) -> tuple[str | None, str]:
    if "/" not in model:
        return None, model
    provider, name = model.split("/", maxsplit=1)
    return provider, name


def _harbor_tool_to_responses_tool(tool: dict[str, Any]) -> dict[str, Any]:
    name = tool.get("name")
    if not isinstance(name, str) or not name:
        raise HarborAgentError("Harbor tool requires a name")
    parameters = tool.get("parameters", {"type": "object", "properties": {}})
    if not isinstance(parameters, dict):
        raise HarborAgentError(f"Harbor tool {name} has non-object parameters")
    description = tool.get("description", "")
    if not isinstance(description, str):
        raise HarborAgentError(f"Harbor tool {name} has non-string description")
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": parameters,
    }


def responses_function_call_to_harbor_action(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("type") != "function_call":
        raise HarborAgentError(f"expected function_call item, got {item.get('type')!r}")
    name = item.get("name")
    call_id = item.get("call_id")
    arguments = item.get("arguments", "{}")
    if not isinstance(name, str) or not name:
        raise HarborAgentError("function_call requires name")
    if not isinstance(call_id, str) or not call_id:
        raise HarborAgentError("function_call requires call_id")
    if not isinstance(arguments, str):
        raise HarborAgentError("function_call arguments must be a JSON string")
    try:
        decoded_arguments = json.loads(arguments)
    except json.JSONDecodeError as error:
        raise HarborAgentError(f"invalid function_call arguments: {error}") from error
    if not isinstance(decoded_arguments, dict):
        raise HarborAgentError("function_call arguments must decode to an object")
    return {
        "type": "tool_action",
        "tool": name,
        "call_id": call_id,
        "arguments": decoded_arguments,
    }


async def _execute_function_call(item: dict[str, Any], *, environment: Any) -> dict[str, Any]:
    action = responses_function_call_to_harbor_action(item)
    tool_name = action["tool"]
    if tool_name not in {"terminal_run", "bash", "shell"}:
        raise HarborAgentError(f"unsupported function_call tool: {tool_name}")

    arguments = action["arguments"]
    command = arguments.get("command", arguments.get("cmd"))
    if not isinstance(command, str) or not command:
        raise HarborAgentError(f"{tool_name} requires command")

    result = await environment.exec(
        command,
        cwd=_optional_str(arguments, "cwd"),
        env=_optional_env(arguments),
        timeout_sec=_optional_int(arguments, "timeout_sec"),
        user=arguments.get("user"),
    )
    return {
        "type": "function_call_output",
        "call_id": action["call_id"],
        "output": json.dumps(
            {
                "stdout": getattr(result, "stdout", None),
                "stderr": getattr(result, "stderr", None),
                "return_code": getattr(result, "return_code"),
            },
            sort_keys=True,
        ),
    }


def _optional_str(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HarborAgentError(f"{key} must be a string")
    return value


def _optional_int(arguments: dict[str, Any], key: str) -> int | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise HarborAgentError(f"{key} must be an integer")
    return value


def _optional_env(arguments: dict[str, Any]) -> dict[str, str] | None:
    value = arguments.get("env")
    if value is None:
        return None
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise HarborAgentError("env must be an object with string values")
    return value


def _populate_context_from_response(context: Any, response: dict[str, Any]) -> None:
    usage = response.get("usage") or {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    if isinstance(input_tokens, int):
        context.n_input_tokens = input_tokens
    if isinstance(output_tokens, int):
        context.n_output_tokens = output_tokens

    metadata = getattr(context, "metadata", None)
    if metadata is None:
        metadata = {}
        context.metadata = metadata
    metadata["final_response_id"] = response.get("id")
    metadata["final_message"] = _extract_final_message(response)
    metadata["usage"] = usage


def _extract_final_message(response: dict[str, Any]) -> str | None:
    texts: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                texts.append(text)
    if not texts:
        return None
    return "\n".join(texts)


async def _post_responses_request(
    agent: GLM52HarborAgent,
    request: dict[str, Any],
) -> dict[str, Any]:
    return await asyncio.to_thread(_post_responses_request_sync, agent, request)


def _post_responses_request_sync(
    agent: GLM52HarborAgent,
    payload: dict[str, Any],
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    endpoint = agent.responses_base_url.rstrip("/") + "/responses"
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("RESPONSES_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib_request.Request(endpoint, data=body, headers=headers, method="POST")
    with urllib_request.urlopen(req, timeout=120) as response:
        decoded = json.loads(response.read().decode("utf-8"))
    if not isinstance(decoded, dict):
        raise HarborAgentError("responses endpoint returned a non-object payload")
    return decoded


def write_trial_artifact(
    artifact_dir: Path,
    *,
    task_id: str,
    trial_id: str,
    model_id: str,
    responses_base_url: str,
    local_host_route: str,
    environment_provider: str,
    events: list[dict[str, Any]],
) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "agent_version": AGENT_VERSION,
        "task_id": task_id,
        "trial_id": trial_id,
        "model_id": model_id,
        "responses_base_url": responses_base_url,
        "local_host_route": local_host_route,
        "environment_provider": environment_provider,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "events": events,
    }
    path = artifact_dir / f"{trial_id}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path
