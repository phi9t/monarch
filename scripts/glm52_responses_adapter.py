# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from typing import Any


DEFAULT_MODEL = "zai-org/GLM-5.2"
DEFAULT_CHAT_BASE_URL = "http://localhost:8000/v1"


class AdapterError(RuntimeError):
    def __init__(self, message: str, *, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class AdapterConfig:
    host: str
    port: int
    model: str
    chat_base_url: str
    api_key_env: str
    timeout_seconds: float


@dataclass(frozen=True)
class ChatResult:
    response: dict[str, Any]
    messages: list[dict[str, Any]]


class ConversationStore:
    def __init__(self) -> None:
        self._messages_by_response_id: dict[str, list[dict[str, Any]]] = {}

    def get(self, response_id: str) -> list[dict[str, Any]]:
        if response_id not in self._messages_by_response_id:
            raise AdapterError(f"unknown previous_response_id: {response_id}")
        return [dict(message) for message in self._messages_by_response_id[response_id]]

    def put(self, response_id: str, messages: list[dict[str, Any]]) -> None:
        self._messages_by_response_id[response_id] = [dict(message) for message in messages]


def join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def response_id() -> str:
    return f"resp_{uuid.uuid4().hex}"


def item_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def response_shell(*, rid: str, model: str, output: list[dict[str, Any]] | None = None, status: str = "completed") -> dict[str, Any]:
    output = output or []
    return {
        "id": rid,
        "object": "response",
        "created_at": int(time.time()),
        "model": model,
        "status": status,
        "output": output,
        "output_text": output_text(output),
    }


def output_text(output: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in output:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "".join(parts)


def responses_to_chat_payload(
    payload: dict[str, Any],
    *,
    default_model: str,
    previous_messages: list[dict[str, Any]] | None = None,
    previous_calls: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    model = str(payload.get("model") or default_model)
    messages = [dict(message) for message in previous_messages or []]
    if not messages and isinstance(payload.get("instructions"), str) and payload["instructions"]:
        messages.append({"role": "system", "content": payload["instructions"]})
    messages.extend(input_to_chat_messages(payload.get("input"), previous_calls=previous_calls))

    chat_payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": bool(payload.get("stream", False)),
        "chat_template_kwargs": chat_template_kwargs(payload),
    }
    if "max_output_tokens" in payload:
        chat_payload["max_tokens"] = payload["max_output_tokens"]
    elif "max_tokens" in payload:
        chat_payload["max_tokens"] = payload["max_tokens"]
    if "temperature" in payload:
        chat_payload["temperature"] = payload["temperature"]
    if "top_p" in payload:
        chat_payload["top_p"] = payload["top_p"]

    tools = responses_tools_to_chat_tools(payload.get("tools"))
    if tools:
        chat_payload["tools"] = tools
    if "tool_choice" in payload:
        chat_payload["tool_choice"] = responses_tool_choice_to_chat(payload["tool_choice"])
    return chat_payload


def responses_request_to_chat_request(
    payload: dict[str, Any],
    *,
    default_model: str = DEFAULT_MODEL,
    previous_messages: list[dict[str, Any]] | None = None,
    previous_calls: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return responses_to_chat_payload(
        payload,
        default_model=default_model,
        previous_messages=previous_messages,
        previous_calls=previous_calls,
    )


def chat_template_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("chat_template_kwargs")
    kwargs = dict(raw) if isinstance(raw, dict) else {}
    kwargs.setdefault("enable_thinking", False)
    return kwargs


def input_to_chat_messages(value: Any, *, previous_calls: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str):
        return [{"role": "user", "content": value}]
    if not isinstance(value, list):
        raise AdapterError("Responses input must be a string, a list, or null")

    messages: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise AdapterError("Responses input list items must be objects")
        item_type = item.get("type")
        if item_type == "function_call_output":
            call_id = item.get("call_id")
            if not isinstance(call_id, str) or not call_id:
                raise AdapterError("function_call_output requires call_id")
            if previous_calls and call_id in previous_calls:
                messages.append(previous_call_to_assistant_message(call_id, previous_calls[call_id]))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": stringify_content(item.get("output", "")),
                }
            )
            continue
        if item_type == "message" or "role" in item:
            role = item.get("role")
            if role not in {"system", "user", "assistant", "tool"}:
                raise AdapterError(f"unsupported message role: {role}")
            message: dict[str, Any] = {"role": role, "content": content_text(item.get("content"))}
            if role == "tool" and isinstance(item.get("tool_call_id"), str):
                message["tool_call_id"] = item["tool_call_id"]
            messages.append(message)
            continue
        if item_type == "function_call":
            messages.append(function_call_item_to_assistant_message(item))
            continue
        raise AdapterError(f"unsupported Responses input item type: {item_type}")
    return messages


def stringify_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for part in value:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and part.get("type") in {"input_text", "output_text", "text"}:
                    parts.append(text)
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    if value is None:
        return ""
    return stringify_content(value)


def previous_call_to_assistant_message(call_id: str, call: dict[str, Any]) -> dict[str, Any]:
    name = call.get("name")
    if not isinstance(name, str) or not name:
        raise AdapterError("previous function call requires name")
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": str(call.get("arguments") or "{}"),
                },
            }
        ],
    }


def function_call_item_to_assistant_message(item: dict[str, Any]) -> dict[str, Any]:
    name = item.get("name")
    if not isinstance(name, str) or not name:
        raise AdapterError("function_call input item requires name")
    call_id = str(item.get("call_id") or item.get("id") or item_id("call"))
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": str(item.get("arguments") or "{}"),
                },
            }
        ],
    }


def responses_tools_to_chat_tools(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AdapterError("tools must be a list")
    tools: list[dict[str, Any]] = []
    for tool in value:
        if not isinstance(tool, dict):
            raise AdapterError("tool entries must be objects")
        if tool.get("type") != "function":
            continue
        function = tool.get("function")
        if isinstance(function, dict):
            tools.append({"type": "function", "function": dict(function)})
            continue
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            raise AdapterError("function tool requires name")
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(tool.get("description") or ""),
                    "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
                },
            }
        )
    return tools


def responses_tool_choice_to_chat(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if value.get("type") == "function" and isinstance(value.get("name"), str):
        return {"type": "function", "function": {"name": value["name"]}}
    return value


def chat_message_to_response_output(message: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    text = chat_text(message)
    if text:
        output.append(
            {
                "id": item_id("msg"),
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        )

    for index, raw_call in enumerate(message.get("tool_calls") or []):
        call = chat_tool_call_to_response_item(raw_call, index)
        output.append(call)

    return output


def chat_response_to_responses_response(chat_response: dict[str, Any], *, include_item_metadata: bool = False) -> dict[str, Any]:
    message = chat_choice_message(chat_response)
    output = chat_message_to_response_output(message)
    if not include_item_metadata:
        output = [minimal_response_output_item(item) for item in output]
    response = response_shell(
        rid=response_id(),
        model=str(chat_response.get("model") or DEFAULT_MODEL),
        output=output,
    )
    usage = responses_usage(chat_response.get("usage"))
    if usage:
        response["usage"] = usage
    return response


def minimal_response_output_item(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("type") == "message":
        content = []
        for part in item.get("content") or []:
            if isinstance(part, dict):
                minimal_part = {"type": part.get("type")}
                if "text" in part:
                    minimal_part["text"] = part["text"]
                content.append(minimal_part)
        return {"type": "message", "role": item.get("role"), "content": content}
    if item.get("type") == "function_call":
        return {
            "type": "function_call",
            "call_id": item.get("call_id"),
            "name": item.get("name"),
            "arguments": item.get("arguments"),
        }
    return dict(item)


def responses_usage(usage: Any) -> dict[str, Any] | None:
    if not isinstance(usage, dict):
        return None
    mapped: dict[str, Any] = {}
    if "prompt_tokens" in usage:
        mapped["input_tokens"] = usage["prompt_tokens"]
    if "completion_tokens" in usage:
        mapped["output_tokens"] = usage["completion_tokens"]
    if "total_tokens" in usage:
        mapped["total_tokens"] = usage["total_tokens"]
    return mapped or dict(usage)


def chat_tool_call_to_response_item(raw_call: dict[str, Any], index: int) -> dict[str, Any]:
    function = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else {}
    call_id = str(raw_call.get("id") or item_id("call"))
    arguments = str(function.get("arguments") or "{}")
    validate_function_call_arguments(arguments)
    return {
        "id": item_id("fc"),
        "type": "function_call",
        "status": "completed",
        "call_id": call_id,
        "name": str(function.get("name") or ""),
        "arguments": arguments,
        "index": index,
    }


def validate_function_call_arguments(arguments: str) -> None:
    try:
        json.loads(arguments)
    except json.JSONDecodeError as error:
        raise AdapterError(f"invalid function_call arguments: {arguments}") from error


def chat_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str):
        return reasoning
    return ""


def chat_assistant_message(message: dict[str, Any]) -> dict[str, Any]:
    assistant = {"role": "assistant", "content": message.get("content")}
    if message.get("tool_calls"):
        assistant["tool_calls"] = message["tool_calls"]
    if message.get("reasoning_content"):
        assistant["reasoning_content"] = message["reasoning_content"]
    return assistant


def post_chat_completion(config: AdapterConfig, payload: dict[str, Any]) -> dict[str, Any]:
    data = json_bytes(payload)
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get(config.api_key_env)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        join_url(config.chat_base_url, "/chat/completions"),
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        raise AdapterError(f"downstream Chat Completions error HTTP {error.code}: {body[:2000]}", status=HTTPStatus.BAD_GATEWAY) from error
    except urllib.error.URLError as error:
        raise AdapterError(f"downstream Chat Completions request failed: {error}", status=HTTPStatus.BAD_GATEWAY) from error


def open_chat_stream(config: AdapterConfig, payload: dict[str, Any]):
    data = json_bytes(payload)
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    api_key = os.environ.get(config.api_key_env)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        join_url(config.chat_base_url, "/chat/completions"),
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        return urllib.request.urlopen(request, timeout=config.timeout_seconds)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        raise AdapterError(f"downstream Chat Completions stream error HTTP {error.code}: {body[:2000]}", status=HTTPStatus.BAD_GATEWAY) from error
    except urllib.error.URLError as error:
        raise AdapterError(f"downstream Chat Completions stream failed: {error}", status=HTTPStatus.BAD_GATEWAY) from error


def run_nonstream_response(config: AdapterConfig, store: ConversationStore, payload: dict[str, Any]) -> ChatResult:
    previous_messages = previous_chat_messages(store, payload)
    chat_payload = responses_to_chat_payload(payload, default_model=config.model, previous_messages=previous_messages)
    chat_payload["stream"] = False
    chat_response = post_chat_completion(config, chat_payload)
    message = chat_choice_message(chat_response)
    response = chat_response_to_responses_response(chat_response, include_item_metadata=True)
    response["model"] = str(chat_payload["model"])
    rid = str(response["id"])

    messages = list(chat_payload["messages"])
    messages.append(chat_assistant_message(message))
    store.put(rid, messages)
    return ChatResult(response=response, messages=messages)


def previous_chat_messages(store: ConversationStore, payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    previous_response_id = payload.get("previous_response_id")
    if previous_response_id is None:
        return None
    if not isinstance(previous_response_id, str) or not previous_response_id:
        raise AdapterError("previous_response_id must be a non-empty string")
    return store.get(previous_response_id)


def chat_choice_message(chat_response: dict[str, Any]) -> dict[str, Any]:
    choices = chat_response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AdapterError("downstream Chat Completions response has no choices", status=HTTPStatus.BAD_GATEWAY)
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise AdapterError("downstream Chat Completions choice has no message", status=HTTPStatus.BAD_GATEWAY)
    return message


def parse_sse_data_events(lines: Any) -> Any:
    current: list[str] = []
    for raw_line in lines:
        line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if current:
                data = "\n".join(current)
                current = []
                if data == "[DONE]":
                    return
                yield json.loads(data)
            continue
        if line.startswith("data:"):
            current.append(line.removeprefix("data:").strip())
    if current:
        data = "\n".join(current)
        if data != "[DONE]":
            yield json.loads(data)


def sse_payload(event: dict[str, Any]) -> bytes:
    return b"data: " + json_bytes(event) + b"\n\n"


def sse_done() -> bytes:
    return b"data: [DONE]\n\n"


def chat_stream_to_responses_events(
    chat_chunks: Any,
    *,
    rid: str | None = None,
    model: str = DEFAULT_MODEL,
) -> Any:
    rid = rid or response_id()
    yield {"type": "response.created", "response": response_shell(rid=rid, model=model, status="in_progress")}

    text_parts: list[str] = []
    tool_calls: dict[int, dict[str, str]] = {}
    tool_item_ids: dict[int, str] = {}
    tool_order: list[int] = []
    message_item_id: str | None = None
    output_entries: list[tuple[str, int | None]] = []

    for event in chat_chunks:
        choices = event.get("choices") if isinstance(event, dict) else None
        if not isinstance(choices, list) or not choices:
            continue
        delta = choices[0].get("delta") or {}
        if not isinstance(delta, dict):
            continue

        content = delta.get("content")
        if isinstance(content, str) and content:
            if message_item_id is None:
                message_item_id = item_id("msg")
                output_entries.append(("message", None))
                yield {
                    "type": "response.output_item.added",
                    "output_index": len(output_entries) - 1,
                    "item": {"id": message_item_id, "type": "message", "role": "assistant", "status": "in_progress", "content": []},
                }
            text_parts.append(content)
            yield {"type": "response.output_text.delta", "item_id": message_item_id, "output_index": output_entries.index(("message", None)), "delta": content}

        for raw_call in delta.get("tool_calls") or []:
            if not isinstance(raw_call, dict):
                continue
            index = int(raw_call.get("index") or 0)
            function = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else {}
            call = tool_calls.setdefault(
                index,
                {
                    "call_id": str(raw_call.get("id") or item_id("call")),
                    "name": "",
                    "arguments": "",
                },
            )
            if function.get("name"):
                call["name"] = str(function["name"])
            if index not in tool_item_ids:
                tool_item_ids[index] = item_id("fc")
                tool_order.append(index)
                output_entries.append(("tool", index))
                yield {
                    "type": "response.output_item.added",
                    "output_index": len(output_entries) - 1,
                    "item": {
                        "id": tool_item_ids[index],
                        "type": "function_call",
                        "status": "in_progress",
                        "call_id": call["call_id"],
                        "name": call["name"],
                        "arguments": "",
                    },
                }
            if function.get("arguments"):
                argument_delta = str(function["arguments"])
                call["arguments"] += argument_delta
                yield {
                    "type": "response.function_call_arguments.delta",
                    "item_id": tool_item_ids[index],
                    "output_index": output_entries.index(("tool", index)),
                    "delta": argument_delta,
                }

    output: list[dict[str, Any]] = []
    text = "".join(text_parts)
    for output_index, (entry_type, tool_index) in enumerate(output_entries):
        if entry_type == "message":
            item = {
                "id": message_item_id or item_id("msg"),
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
            output.append(item)
            yield {"type": "response.output_item.done", "output_index": output_index, "item": item}
            continue

        if tool_index is None:
            continue
        call = tool_calls[tool_index]
        arguments = call["arguments"] or "{}"
        validate_function_call_arguments(arguments)
        item = {
            "id": tool_item_ids[tool_index],
            "type": "function_call",
            "status": "completed",
            "call_id": call["call_id"],
            "name": call["name"],
            "arguments": arguments,
        }
        output.append(item)
        yield {
            "type": "response.function_call_arguments.done",
            "item_id": tool_item_ids[tool_index],
            "output_index": output_index,
            "arguments": arguments,
        }
        yield {"type": "response.output_item.done", "output_index": output_index, "item": item}

    yield {"type": "response.completed", "response": response_shell(rid=rid, model=model, output=output)}


def stream_response_events(config: AdapterConfig, store: ConversationStore, payload: dict[str, Any]) -> Any:
    previous_messages = previous_chat_messages(store, payload)
    chat_payload = responses_to_chat_payload(payload, default_model=config.model, previous_messages=previous_messages)
    chat_payload["stream"] = True
    rid = response_id()
    model = str(chat_payload["model"])
    messages = list(chat_payload["messages"])
    completed: dict[str, Any] | None = None

    with open_chat_stream(config, chat_payload) as response:
        for event in chat_stream_to_responses_events(parse_sse_data_events(response), rid=rid, model=model):
            if event.get("type") == "response.completed":
                completed = event.get("response")
            yield event

    output = completed.get("output", []) if isinstance(completed, dict) else []
    assistant = response_output_to_chat_assistant(output)
    messages.append(assistant)
    store.put(rid, messages)


def response_output_to_chat_assistant(output: Any) -> dict[str, Any]:
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for item in output or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for content in item.get("content") or []:
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    text_parts.append(content["text"])
        elif item.get("type") == "function_call":
            tool_calls.append(
                {
                    "id": item.get("call_id"),
                    "type": "function",
                    "function": {
                        "name": item.get("name") or "",
                        "arguments": item.get("arguments") or "{}",
                    },
                }
            )
    assistant: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts) or None}
    if tool_calls:
        assistant["tool_calls"] = tool_calls
    return assistant


class ResponsesAdapterHandler(BaseHTTPRequestHandler):
    server_version = "glm52-responses-adapter/1"

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/v1/models":
            self.write_json(
                HTTPStatus.OK,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": self.server.config.model,
                            "object": "model",
                            "created": 0,
                            "owned_by": "glm52-responses-adapter",
                        }
                    ],
                },
            )
            return
        self.write_json(HTTPStatus.NOT_FOUND, error_payload(f"unknown route: {self.path}"))

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/v1/responses":
            self.write_json(HTTPStatus.NOT_FOUND, error_payload(f"unknown route: {self.path}"))
            return

        try:
            payload = self.read_payload()
            if bool(payload.get("stream", False)):
                self.write_stream(payload)
            else:
                result = run_nonstream_response(self.server.config, self.server.store, payload)
                self.write_json(HTTPStatus.OK, result.response)
        except AdapterError as error:
            self.write_json(error.status, error_payload(str(error)))
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            self.write_json(HTTPStatus.INTERNAL_SERVER_ERROR, error_payload(f"internal adapter error: {error}"))

    def read_payload(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise AdapterError(f"invalid JSON request body: {error}") from error
        if not isinstance(payload, dict):
            raise AdapterError("request body must be a JSON object")
        return payload

    def write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json_bytes(payload) + b"\n"
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_stream(self, payload: dict[str, Any]) -> None:
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for event in stream_response_events(self.server.config, self.server.store, payload):
                self.wfile.write(sse_payload(event))
                self.wfile.flush()
            self.wfile.write(sse_done())
            self.wfile.flush()
            self.close_connection = True
        except AdapterError as error:
            self.wfile.write(sse_payload({"type": "error", "error": {"message": str(error)}}))
            self.wfile.flush()
            self.close_connection = True

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}", file=sys.stderr)


class ResponsesAdapterServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler], config: AdapterConfig) -> None:
        super().__init__(server_address, handler_class)
        self.config = config
        self.store = ConversationStore()


def error_payload(message: str) -> dict[str, Any]:
    return {"error": {"type": "invalid_request_error", "message": message}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve an OpenAI Responses-compatible adapter for GLM-5.2 Chat Completions.")
    parser.add_argument("--host", default=os.environ.get("GLM52_RESPONSES_ADAPTER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("GLM52_RESPONSES_ADAPTER_PORT", "8080")))
    parser.add_argument("--model", default=os.environ.get("GLM52_MODEL", DEFAULT_MODEL))
    parser.add_argument("--chat-base-url", default=os.environ.get("GLM52_CHAT_BASE_URL", DEFAULT_CHAT_BASE_URL))
    parser.add_argument("--api-key-env", default=os.environ.get("GLM52_API_KEY_ENV", "GLM_API_KEY"))
    parser.add_argument("--timeout-seconds", type=float, default=float(os.environ.get("GLM52_ADAPTER_TIMEOUT_SECONDS", "300")))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = AdapterConfig(
        host=args.host,
        port=args.port,
        model=args.model,
        chat_base_url=args.chat_base_url,
        api_key_env=args.api_key_env,
        timeout_seconds=args.timeout_seconds,
    )
    server = ResponsesAdapterServer((config.host, config.port), ResponsesAdapterHandler, config)
    print(
        f"serving GLM-5.2 Responses adapter on http://{config.host}:{config.port}/v1 "
        f"-> {config.chat_base_url.rstrip('/')}/chat/completions",
        file=sys.stderr,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
