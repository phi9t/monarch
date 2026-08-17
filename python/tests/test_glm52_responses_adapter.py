# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


HELPER_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "glm52_responses_adapter.py"
)
spec = importlib.util.spec_from_file_location("glm52_responses_adapter", HELPER_PATH)
assert spec is not None
assert spec.loader is not None
glm52_responses_adapter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = glm52_responses_adapter
spec.loader.exec_module(glm52_responses_adapter)


def _helper(*names: str) -> Any:
    for name in names:
        value = getattr(glm52_responses_adapter, name, None)
        if value is not None:
            return value
    pytest.fail(
        "glm52_responses_adapter must expose one of: " + ", ".join(names)
    )


def _call_helper(names: tuple[str, ...], *args: Any, **kwargs: Any) -> Any:
    helper = _helper(*names)

    try:
        return helper(*args, **kwargs)
    except TypeError as error:
        if kwargs:
            try:
                return helper(*args)
            except TypeError:
                pass
        if "takes" not in str(error) and "argument" not in str(error):
            raise
        raise


def _event_payloads(events: Any) -> list[dict[str, Any]]:
    if isinstance(events, str):
        events = [events]

    payloads = []
    for event in events:
        if isinstance(event, dict):
            payloads.append(event)
            continue

        assert isinstance(event, str)
        for block in event.strip().split("\n\n"):
            data_lines = [
                line.removeprefix("data: ").strip()
                for line in block.splitlines()
                if line.startswith("data:")
            ]
            for data in data_lines:
                if data and data != "[DONE]":
                    payloads.append(json.loads(data))

    return payloads


def _extract_chat_request(converted: Any) -> dict[str, Any]:
    if isinstance(converted, tuple):
        converted = converted[0]
    assert isinstance(converted, dict)
    return converted


def test_responses_request_converts_to_chat_completion_request() -> None:
    convert_request = _helper(
        "responses_request_to_chat_request",
        "convert_responses_request_to_chat_request",
        "to_chat_request",
    )
    request = {
        "model": "glm-5.2",
        "instructions": "Answer with precise file names.",
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Read README.md."},
                    {"type": "input_text", "text": "Then report risks."},
                ],
            }
        ],
        "tools": [
            {
                "type": "function",
                "name": "read_project_file",
                "description": "Read one project file.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            }
        ],
        "max_output_tokens": 256,
        "temperature": 0,
        "stream": False,
    }

    chat_request = _extract_chat_request(convert_request(request))

    assert chat_request["model"] == "glm-5.2"
    assert chat_request["messages"] == [
        {"role": "system", "content": "Answer with precise file names."},
        {"role": "user", "content": "Read README.md.\nThen report risks."},
    ]
    assert chat_request["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "read_project_file",
                "description": "Read one project file.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }
    ]
    assert chat_request["max_tokens"] == 256
    assert chat_request["temperature"] == 0
    assert chat_request["stream"] is False


def test_chat_nonstream_response_converts_to_responses_shape() -> None:
    convert_response = _helper(
        "chat_response_to_responses_response",
        "convert_chat_response_to_responses_response",
        "to_responses_response",
    )
    chat_response = {
        "id": "chatcmpl_123",
        "model": "glm-5.2",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "I need README.md first.",
                    "tool_calls": [
                        {
                            "id": "call_readme",
                            "type": "function",
                            "function": {
                                "name": "read_project_file",
                                "arguments": "{\"path\": \"README.md\"}",
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {
            "prompt_tokens": 17,
            "completion_tokens": 9,
            "total_tokens": 26,
        },
    }

    response = convert_response(chat_response)

    assert response["object"] == "response"
    assert response["model"] == "glm-5.2"
    assert response["status"] in {"completed", "requires_action"}
    assert response["output_text"] == "I need README.md first."
    assert {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "I need README.md first."}],
    } in response["output"]
    assert {
        "type": "function_call",
        "call_id": "call_readme",
        "name": "read_project_file",
        "arguments": "{\"path\": \"README.md\"}",
    } in response["output"]
    assert response["usage"] == {
        "input_tokens": 17,
        "output_tokens": 9,
        "total_tokens": 26,
    }


def test_chat_nonstream_response_rejects_malformed_tool_arguments() -> None:
    convert_response = _helper(
        "chat_response_to_responses_response",
        "convert_chat_response_to_responses_response",
        "to_responses_response",
    )
    chat_response = {
        "id": "chatcmpl_bad_args",
        "model": "glm-5.2",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_bad",
                            "type": "function",
                            "function": {
                                "name": "read_project_file",
                                "arguments": "{\"path\": ",
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }

    with pytest.raises(
        glm52_responses_adapter.AdapterError,
        match="invalid function_call arguments",
    ):
        convert_response(chat_response)


def test_chat_streaming_tool_call_deltas_convert_to_responses_sse_events() -> None:
    convert_stream = _helper(
        "chat_stream_to_responses_events",
        "convert_chat_stream_to_responses_events",
        "chat_stream_chunks_to_responses_events",
    )
    chat_chunks = [
        {
            "id": "chatcmpl_456",
            "model": "glm-5.2",
            "choices": [{"delta": {"role": "assistant"}, "finish_reason": None}],
        },
        {
            "id": "chatcmpl_456",
            "model": "glm-5.2",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_readme",
                                "type": "function",
                                "function": {
                                    "name": "read_project_file",
                                    "arguments": "{\"path\": ",
                                },
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl_456",
            "model": "glm-5.2",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": "\"README.md\"}"},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl_456",
            "model": "glm-5.2",
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
        },
    ]

    payloads = _event_payloads(convert_stream(chat_chunks))

    assert payloads[0]["type"] == "response.created"
    assert payloads[0]["response"]["object"] == "response"
    assert {
        "type": "response.output_item.added",
        "item": {
            "type": "function_call",
            "call_id": "call_readme",
            "name": "read_project_file",
        },
    } in [
        {
            "type": payload["type"],
            "item": {
                "type": payload["item"]["type"],
                "call_id": payload["item"]["call_id"],
                "name": payload["item"]["name"],
            },
        }
        for payload in payloads
        if payload["type"] == "response.output_item.added"
    ]
    assert [
        payload["delta"]
        for payload in payloads
        if payload["type"] == "response.function_call_arguments.delta"
    ] == ["{\"path\": ", "\"README.md\"}"]
    assert payloads[-1]["type"] == "response.completed"


def test_chat_streaming_rejects_malformed_tool_arguments() -> None:
    convert_stream = _helper(
        "chat_stream_to_responses_events",
        "convert_chat_stream_to_responses_events",
        "chat_stream_chunks_to_responses_events",
    )
    chat_chunks = [
        {
            "id": "chatcmpl_bad_stream_args",
            "model": "glm-5.2",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_bad",
                                "type": "function",
                                "function": {
                                    "name": "read_project_file",
                                    "arguments": "{\"path\": ",
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
    ]

    with pytest.raises(
        glm52_responses_adapter.AdapterError,
        match="invalid function_call arguments",
    ):
        list(convert_stream(chat_chunks))


def test_chat_streaming_mixed_text_and_tool_calls_keep_stable_output_indexes() -> None:
    convert_stream = _helper(
        "chat_stream_to_responses_events",
        "convert_chat_stream_to_responses_events",
        "chat_stream_chunks_to_responses_events",
    )
    chat_chunks = [
        {
            "id": "chatcmpl_789",
            "model": "glm-5.2",
            "choices": [{"delta": {"content": "I will inspect it first."}}],
        },
        {
            "id": "chatcmpl_789",
            "model": "glm-5.2",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_readme",
                                "function": {
                                    "name": "read_project_file",
                                    "arguments": "{\"path\": \"README.md\"}",
                                },
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        },
    ]

    payloads = _event_payloads(convert_stream(chat_chunks))
    added = [
        (payload["output_index"], payload["item"]["type"], payload["item"]["id"])
        for payload in payloads
        if payload["type"] == "response.output_item.added"
    ]
    done = [
        (payload["output_index"], payload["item"]["type"], payload["item"]["id"])
        for payload in payloads
        if payload["type"] == "response.output_item.done"
    ]

    assert [(index, item_type) for index, item_type, _ in added] == [
        (0, "message"),
        (1, "function_call"),
    ]
    assert done == added
    completed = payloads[-1]["response"]
    assert [item["type"] for item in completed["output"]] == [
        "message",
        "function_call",
    ]


def test_function_call_output_continuation_converts_to_chat_tool_message() -> None:
    convert_request = _helper(
        "responses_request_to_chat_request",
        "convert_responses_request_to_chat_request",
        "to_chat_request",
    )
    request = {
        "model": "glm-5.2",
        "previous_response_id": "resp_previous",
        "input": [
            {
                "type": "function_call_output",
                "call_id": "call_readme",
                "output": "{\"path\": \"README.md\", \"contents\": \"Monarch\"}",
            }
        ],
    }
    previous_calls = {
        "call_readme": {
            "name": "read_project_file",
            "arguments": "{\"path\": \"README.md\"}",
        }
    }

    chat_request = _extract_chat_request(
        _call_helper(
            (
                "responses_request_to_chat_request",
                "convert_responses_request_to_chat_request",
                "to_chat_request",
            ),
            request,
            previous_calls=previous_calls,
        )
    )

    assert chat_request["messages"][-2:] == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_readme",
                    "type": "function",
                    "function": {
                        "name": "read_project_file",
                        "arguments": "{\"path\": \"README.md\"}",
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_readme",
            "content": "{\"path\": \"README.md\", \"contents\": \"Monarch\"}",
        },
    ]


def test_build_parser_reads_documented_adapter_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GLM52_RESPONSES_ADAPTER_HOST", "0.0.0.0")
    monkeypatch.setenv("GLM52_RESPONSES_ADAPTER_PORT", "18080")
    monkeypatch.setenv("GLM52_MODEL", "zai-org/GLM-5.2-test")
    monkeypatch.setenv("GLM52_CHAT_BASE_URL", "http://chat.example/v1")
    monkeypatch.setenv("GLM52_API_KEY_ENV", "GLM_TEST_API_KEY")
    monkeypatch.setenv("GLM52_ADAPTER_TIMEOUT_SECONDS", "12.5")

    args = glm52_responses_adapter.build_parser().parse_args([])

    assert args.host == "0.0.0.0"
    assert args.port == 18080
    assert args.model == "zai-org/GLM-5.2-test"
    assert args.chat_base_url == "http://chat.example/v1"
    assert args.api_key_env == "GLM_TEST_API_KEY"
    assert args.timeout_seconds == 12.5
