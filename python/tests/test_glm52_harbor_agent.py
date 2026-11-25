# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import importlib.util
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace


HELPER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "glm52_harbor_agent.py"
spec = importlib.util.spec_from_file_location("glm52_harbor_agent", HELPER_PATH)
assert spec is not None
assert spec.loader is not None
glm52_harbor_agent = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = glm52_harbor_agent
spec.loader.exec_module(glm52_harbor_agent)

GLM52HarborAgent = glm52_harbor_agent.GLM52HarborAgent
responses_function_call_to_harbor_action = (
    glm52_harbor_agent.responses_function_call_to_harbor_action
)
write_trial_artifact = glm52_harbor_agent.write_trial_artifact


class _FakeHTTPResponse:
    def __init__(self, body: bytes, content_type: str = "application/json") -> None:
        self.body = body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_agent_builds_responses_request_with_codex_profile() -> None:
    agent = GLM52HarborAgent(
        responses_base_url="http://host.docker.internal:8080/v1",
        model="zai-org/GLM-5.2",
        local_host_route="host.docker.internal",
    )

    request = agent.build_responses_request(
        task_instruction="Fix the failing test.",
        observation="pytest says slugify keeps spaces.",
        tools=[
            {
                "name": "terminal_run",
                "description": "Run a command.",
                "parameters": {"type": "object"},
            }
        ],
    )

    assert request["model"] == "zai-org/GLM-5.2"
    assert request["stream"] is True
    assert request["tool_choice"] == "auto"
    assert request["chat_template_kwargs"]["enable_thinking"] is False
    assert request["input"][0]["role"] == "user"
    assert "Fix the failing test." in request["input"][0]["content"][0]["text"]
    assert request["tools"][0]["type"] == "function"


def test_agent_accepts_harbor_factory_kwargs(tmp_path: Path) -> None:
    agent = GLM52HarborAgent(
        logs_dir=tmp_path,
        model_name="zai-org/GLM-5.2",
        responses_base_url="http://host.docker.internal:8080/v1",
        local_host_route="host.docker.internal",
        stream=True,
    )
    agent.session_id = "session-1"
    agent.context_id = "context-1"

    assert isinstance(agent.extra_env, Mapping)
    assert agent.extra_env == {}

    request = agent.build_responses_request(
        task_instruction="Fix the failing test.",
        observation="pytest says slugify keeps spaces.",
        tools=[
            {
                "name": "terminal_run",
                "description": "Run a command.",
                "parameters": {"type": "object"},
            }
        ],
    )
    action = responses_function_call_to_harbor_action(
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "terminal_run",
            "arguments": "{\"command\": \"python -m pytest\"}",
        }
    )

    assert request["model"] == "zai-org/GLM-5.2"
    assert request["stream"] is True
    assert request["tools"][0]["name"] == "terminal_run"
    assert request["input"][0]["role"] == "user"
    assert "Fix the failing test." in request["input"][0]["content"][0]["text"]
    assert agent.session_id == "session-1"
    assert agent.context_id == "context-1"
    assert action == {
        "type": "tool_action",
        "tool": "terminal_run",
        "call_id": "call_1",
        "arguments": {"command": "python -m pytest"},
    }


def test_agent_setup_is_awaitable_and_preserves_request_action_behavior(
    tmp_path: Path,
) -> None:
    agent = GLM52HarborAgent(
        logs_dir=tmp_path,
        model_name="zai-org/GLM-5.2",
        responses_base_url="http://host.docker.internal:8080/v1",
        local_host_route="host.docker.internal",
        stream=True,
    )
    environment = object()

    asyncio.run(agent.setup(environment=environment))

    request = agent.build_responses_request(
        task_instruction="Fix the failing test.",
        observation="pytest says slugify keeps spaces.",
        tools=[
            {
                "name": "terminal_run",
                "description": "Run a command.",
                "parameters": {"type": "object"},
            }
        ],
    )
    action = responses_function_call_to_harbor_action(
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "terminal_run",
            "arguments": "{\"command\": \"python -m pytest\"}",
        }
    )

    assert request["model"] == "zai-org/GLM-5.2"
    assert request["stream"] is True
    assert request["tools"][0]["name"] == "terminal_run"
    assert action == {
        "type": "tool_action",
        "tool": "terminal_run",
        "call_id": "call_1",
        "arguments": {"command": "python -m pytest"},
    }


def test_agent_populate_context_post_run_accepts_empty_context(
    tmp_path: Path,
) -> None:
    agent = GLM52HarborAgent(
        logs_dir=tmp_path,
        model_name="zai-org/GLM-5.2",
        responses_base_url="http://host.docker.internal:8080/v1",
        local_host_route="host.docker.internal",
        stream=True,
    )
    context = type("FakeContext", (), {})()

    populate_context_post_run = getattr(agent, "populate_context_post_run", None)

    assert callable(populate_context_post_run)
    assert populate_context_post_run(context) is None
    assert vars(context) == {}


def test_agent_run_executes_terminal_tool_and_records_final_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    agent = GLM52HarborAgent(
        logs_dir=tmp_path,
        model_name="zai-org/GLM-5.2",
        responses_base_url="http://host.docker.internal:8080/v1",
        local_host_route="host.docker.internal",
        stream=False,
    )
    responses = [
        {
            "id": "resp_1",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "terminal_run",
                    "arguments": json.dumps(
                        {
                            "command": "printf harbor",
                            "cwd": "/workspace",
                            "timeout_sec": 12,
                        }
                    ),
                }
            ],
        },
        {
            "id": "resp_2",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "finished"},
                    ],
                }
            ],
            "usage": {"input_tokens": 31, "output_tokens": 7},
        },
    ]
    sent_requests = []

    async def fake_post(agent, request):
        sent_requests.append(request)
        return responses[len(sent_requests) - 1]

    monkeypatch.setattr(
        glm52_harbor_agent,
        "_post_responses_request",
        fake_post,
        raising=False,
    )

    class FakeEnvironment:
        def __init__(self) -> None:
            self.calls = []

        async def exec(
            self,
            command,
            cwd=None,
            env=None,
            timeout_sec=None,
            user=None,
        ):
            self.calls.append(
                {
                    "command": command,
                    "cwd": cwd,
                    "env": env,
                    "timeout_sec": timeout_sec,
                    "user": user,
                }
            )
            return SimpleNamespace(stdout="harbor", stderr="", return_code=0)

    environment = FakeEnvironment()
    context = SimpleNamespace(metadata={})

    asyncio.run(
        agent.run(
            instruction="Use the terminal once.",
            environment=environment,
            context=context,
        )
    )

    assert len(sent_requests) == 2
    assert sent_requests[0]["input"][0]["role"] == "user"
    assert "Use the terminal once." in sent_requests[0]["input"][0]["content"][0]["text"]
    assert environment.calls == [
        {
            "command": "printf harbor",
            "cwd": "/workspace",
            "env": None,
            "timeout_sec": 12,
            "user": None,
        }
    ]
    assert sent_requests[1]["previous_response_id"] == "resp_1"
    assert sent_requests[1]["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": json.dumps(
                {
                    "stdout": "harbor",
                    "stderr": "",
                    "return_code": 0,
                },
                sort_keys=True,
            ),
        }
    ]
    assert context.n_input_tokens == 31
    assert context.n_output_tokens == 7
    assert context.metadata["final_response_id"] == "resp_2"
    assert context.metadata["final_message"] == "finished"
    assert context.metadata["usage"] == {"input_tokens": 31, "output_tokens": 7}


def test_agent_run_executes_glm_inline_terminal_tool_calls(
    monkeypatch,
    tmp_path: Path,
) -> None:
    agent = GLM52HarborAgent(
        logs_dir=tmp_path,
        model_name="zai-org/GLM-5.2",
        responses_base_url="http://127.0.0.1:18081/v1",
        local_host_route="127.0.0.1",
        stream=True,
    )
    responses = [
        {
            "id": "resp_1",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                "I will inspect the workspace."
                                "<tool_call>terminal_run"
                                "<arg_key>command</arg_key>"
                                "<arg_value>pwd</arg_value>"
                                "<arg_key>timeout_sec</arg_key>"
                                "<arg_value>5</arg_value>"
                                "</tool_call>"
                            ),
                        }
                    ],
                }
            ],
        },
        {
            "id": "resp_2",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "finished"},
                    ],
                }
            ],
        },
    ]
    sent_requests = []

    async def fake_post(agent, request):
        sent_requests.append(request)
        return responses[len(sent_requests) - 1]

    monkeypatch.setattr(
        glm52_harbor_agent,
        "_post_responses_request",
        fake_post,
        raising=False,
    )

    class FakeEnvironment:
        def __init__(self) -> None:
            self.calls = []

        async def exec(
            self,
            command,
            cwd=None,
            env=None,
            timeout_sec=None,
            user=None,
        ):
            self.calls.append(
                {
                    "command": command,
                    "cwd": cwd,
                    "env": env,
                    "timeout_sec": timeout_sec,
                    "user": user,
                }
            )
            return SimpleNamespace(stdout="/workspace", stderr="", return_code=0)

    environment = FakeEnvironment()
    context = SimpleNamespace(metadata={})

    asyncio.run(
        agent.run(
            instruction="Use the terminal once.",
            environment=environment,
            context=context,
        )
    )

    assert environment.calls == [
        {
            "command": "pwd",
            "cwd": None,
            "env": None,
            "timeout_sec": 5,
            "user": None,
        }
    ]
    assert sent_requests[1]["previous_response_id"] == "resp_1"
    assert sent_requests[1]["input"][0]["type"] == "function_call"
    assert sent_requests[1]["input"][1]["type"] == "function_call_output"
    assert context.metadata["final_response_id"] == "resp_2"


def test_agent_run_records_inflight_request_when_cancelled(
    monkeypatch,
    tmp_path: Path,
) -> None:
    agent = GLM52HarborAgent(
        logs_dir=tmp_path,
        model_name="zai-org/GLM-5.2",
        responses_base_url="http://127.0.0.1:18081/v1",
        responses_timeout_seconds=1800,
        stream=True,
        decoding_profile={
            "temperature": 0.2,
            "top_p": 0.95,
            "max_output_tokens": 4096,
            "glm_thinking": "disabled",
        },
    )
    started = asyncio.Event()

    async def fake_post(agent, request):
        started.set()
        await asyncio.sleep(60)

    monkeypatch.setattr(
        glm52_harbor_agent,
        "_post_responses_request",
        fake_post,
        raising=False,
    )

    async def run_and_cancel():
        context = SimpleNamespace(metadata={})
        task = asyncio.create_task(
            agent.run(
                instruction="Use the terminal once.",
                environment=object(),
                context=context,
            )
        )
        await started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return context

    context = asyncio.run(run_and_cancel())

    in_flight = context.metadata["inflight_responses_request"]
    assert in_flight["stage"] == "initial_request"
    assert in_flight["endpoint"] == "http://127.0.0.1:18081/v1/responses"
    assert in_flight["timeout_seconds"] == 1800
    assert in_flight["stream"] is True
    assert in_flight["input_items"] == 1
    assert in_flight["tools"] == ["terminal_run"]
    assert in_flight["decoding_profile"] == {
        "temperature": 0.2,
        "top_p": 0.95,
        "max_output_tokens": 4096,
        "glm_thinking": "disabled",
    }
    assert in_flight["elapsed_seconds"] >= 0


def test_post_responses_request_accepts_streaming_sse(monkeypatch) -> None:
    agent = GLM52HarborAgent(
        model_name="zai-org/GLM-5.2",
        responses_base_url="http://127.0.0.1:18081/v1",
        responses_timeout_seconds=1800,
        stream=True,
    )
    body = b"".join(
        [
            b'data: {"type":"response.created","response":{"id":"resp_1"}}\n\n',
            b'data: {"type":"response.output_item.done","output_index":0,'
            b'"item":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"done"}]}}\n\n',
            b'data: {"type":"response.completed","response":{"id":"resp_1","output":['
            b'{"type":"message","role":"assistant","content":[{"type":"output_text","text":"done"}]}'
            b'],"usage":{"input_tokens":3,"output_tokens":1}}}\n\n',
            b"data: [DONE]\n\n",
        ]
    )

    def fake_urlopen(request, timeout):
        assert timeout == 1800
        return _FakeHTTPResponse(body, content_type="text/event-stream")

    monkeypatch.setattr(glm52_harbor_agent.urllib_request, "urlopen", fake_urlopen)

    response = glm52_harbor_agent._post_responses_request_sync(
        agent,
        {"model": "zai-org/GLM-5.2", "stream": True},
    )

    assert response["id"] == "resp_1"
    assert response["output"][0]["content"][0]["text"] == "done"
    assert response["usage"] == {"input_tokens": 3, "output_tokens": 1}


def test_post_responses_request_reconstructs_done_stream_without_completed(
    monkeypatch,
) -> None:
    agent = GLM52HarborAgent(
        model_name="zai-org/GLM-5.2",
        responses_base_url="http://127.0.0.1:18081/v1",
        responses_timeout_seconds=1800,
        stream=True,
    )
    body = b"".join(
        [
            b'data: {"type":"response.created","response":{"id":"resp_1","model":"glm-5.2"}}\n\n',
            b'data: {"type":"response.output_item.done","output_index":0,"item":'
            b'{"type":"message","role":"assistant","content":[{"type":"output_text","text":"done"}]}}\n\n',
            b"data: [DONE]\n\n",
        ]
    )

    def fake_urlopen(request, timeout):
        assert timeout == 1800
        return _FakeHTTPResponse(body, content_type="text/event-stream")

    monkeypatch.setattr(glm52_harbor_agent.urllib_request, "urlopen", fake_urlopen)

    response = glm52_harbor_agent._post_responses_request_sync(
        agent,
        {"model": "zai-org/GLM-5.2", "stream": True},
    )

    assert response["id"] == "resp_1"
    assert response["model"] == "glm-5.2"
    assert response["status"] == "completed"
    assert response["output"] == [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "done"}],
        }
    ]


def test_agent_returns_harbor_trial_agent_info(tmp_path: Path) -> None:
    agent = GLM52HarborAgent(
        logs_dir=tmp_path,
        model_name="zai-org/GLM-5.2",
        responses_base_url="http://host.docker.internal:8080/v1",
        local_host_route="host.docker.internal",
        stream=True,
        session_id="session-1",
        context_id="context-1",
    )

    agent_info = agent.to_agent_info()

    assert agent_info.name == "glm52-responses"
    assert agent_info.version == "glm52-harbor-agent-v1"
    assert agent_info.model_info is not None
    assert agent_info.model_info.name == "GLM-5.2"
    assert agent_info.model_info.provider == "zai-org"


def test_responses_function_call_converts_to_harbor_action() -> None:
    action = responses_function_call_to_harbor_action(
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "terminal_run",
            "arguments": "{\"command\": \"python -m pytest\"}",
        }
    )

    assert action == {
        "type": "tool_action",
        "tool": "terminal_run",
        "call_id": "call_1",
        "arguments": {"command": "python -m pytest"},
    }


def test_trial_artifact_records_route_and_endpoint(tmp_path: Path) -> None:
    artifact_path = write_trial_artifact(
        tmp_path,
        task_id="terminal-bench-2/example",
        trial_id="trial-1",
        model_id="zai-org/GLM-5.2",
        responses_base_url="http://host.docker.internal:8080/v1",
        local_host_route="host.docker.internal",
        environment_provider="local_docker",
        events=[{"type": "tool_action", "tool": "terminal_run"}],
    )

    payload = json.loads(artifact_path.read_text())
    assert payload["task_id"] == "terminal-bench-2/example"
    assert payload["trial_id"] == "trial-1"
    assert payload["model_id"] == "zai-org/GLM-5.2"
    assert payload["responses_base_url"] == "http://host.docker.internal:8080/v1"
    assert payload["local_host_route"] == "host.docker.internal"
    assert payload["environment_provider"] == "local_docker"
    assert payload["agent_version"]
