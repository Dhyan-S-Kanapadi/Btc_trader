"""Small OpenAI-compatible Groq adapter for the isolated investigator runtime."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx


class GroqModel:
    """Translate the investigator's typed tool protocol to Groq chat completions."""

    def __init__(
        self,
        api_key: str,
        model_id: str,
        *,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model_id = model_id
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self._tool_results: list[dict[str, object]] = []

    def set_tool_results(self, tool_results: list[dict[str, object]]) -> None:
        self._tool_results = tool_results

    def invoke(self, prompt: str, snapshot: object, tools: dict[str, dict[str, object]]) -> object:
        functions = [
            {"type": "function", "function": {"name": name, "parameters": schema}}
            for name, schema in tools.items()
        ]
        request: dict[str, Any] = {
            "model": self.model_id,
            "temperature": 0.1,
            "max_tokens": 512,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "snapshot": snapshot.model_dump(mode="json"),
                            "tools": tools,
                            "tool_results": self._tool_results,
                        },
                        default=str,
                        separators=(",", ":"),
                    ),
                },
            ],
        }
        if functions:
            request["tools"] = functions
            request["tool_choice"] = "auto"
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=request,
                )
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise RuntimeError("Groq investigator unavailable") from error
        if not isinstance(message, Mapping):
            raise RuntimeError("Groq investigator returned an invalid message")
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and len(tool_calls) == 1:
            function = tool_calls[0].get("function") if isinstance(tool_calls[0], Mapping) else None
            if isinstance(function, Mapping) and isinstance(function.get("name"), str):
                try:
                    arguments = json.loads(str(function.get("arguments", "{}")))
                except json.JSONDecodeError as error:
                    raise RuntimeError(
                        "Groq investigator returned invalid tool arguments"
                    ) from error
                if isinstance(arguments, dict):
                    return {"tool": function["name"], "args": arguments}
        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError("Groq investigator returned no JSON verdict")
        return content
