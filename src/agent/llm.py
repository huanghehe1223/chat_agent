"""DeepSeek chat completions client based on the OpenAI SDK."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Iterator

from openai import APIConnectionError, APIError, APITimeoutError, OpenAI

from src.agent.config import AgentConfig
from src.agent.schemas import AssistantMessage


class LLMError(RuntimeError):
    """Base class for LLM client errors."""


class LLMAPIError(LLMError):
    """Raised when the remote API returns an error or cannot be reached."""


class LLMResponseError(LLMError):
    """Raised when the remote API response does not match the expected shape."""


class DeepSeekClient:
    """Small OpenAI-compatible chat completions client for DeepSeek."""

    def __init__(self, config: AgentConfig, client: OpenAI | None = None) -> None:
        self.config = config
        self.client = client or OpenAI(
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_base_url.rstrip("/"),
            timeout=config.request_timeout,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call DeepSeek and return the assistant message.

        The returned message may contain native OpenAI-compatible ``tool_calls``.
        The runtime will decide whether to execute tools or finish the turn.
        """

        response_data = self.create_chat_completion(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )
        return self._extract_message(response_data)

    def chat_parsed(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> AssistantMessage:
        """Call DeepSeek and parse thinking, final answer, and tool calls."""

        message = self.chat(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )
        return AssistantMessage.from_api_message(message)

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call DeepSeek with streaming enabled and return the merged assistant message.

        This compatibility helper consumes the event stream and returns the final
        message. Runtime code should prefer ``stream_chat_events`` so deltas can
        be displayed and tool calls can be handled as soon as they are complete.
        """

        final_message: dict[str, Any] | None = None
        for event in self.stream_chat_events(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
        ):
            if event["type"] == "message":
                final_message = event["message"]

        if final_message is None:
            raise LLMResponseError("DeepSeek stream response missing final message.")
        return final_message

    def chat_stream_parsed(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> AssistantMessage:
        """Call DeepSeek with streaming enabled and parse the merged assistant message."""

        message = self.chat_stream(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )
        return AssistantMessage.from_api_message(message)

    def create_chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call the chat completions endpoint and return the raw response as a dict."""

        if not messages:
            raise LLMResponseError("messages must contain at least one message.")

        request_kwargs = self._build_request_kwargs(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
            stream=False,
        )

        try:
            response = self.client.chat.completions.create(**request_kwargs)
        except (APIConnectionError, APITimeoutError) as exc:
            raise LLMAPIError(f"DeepSeek request failed: {exc}") from exc
        except APIError as exc:
            raise LLMAPIError(f"DeepSeek API returned an error: {exc}") from exc

        return response.model_dump(exclude_none=True)

    def stream_chat_events(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield parsed streaming events as chunks arrive.

        Event types:
        - ``reasoning_delta``: incremental thinking text.
        - ``content_delta``: incremental final-answer text.
        - ``tool_call_delta``: partial tool-call data for debugging/UI.
        - ``tool_call``: complete tool call, ready for runtime execution.
        - ``message``: final merged assistant message for local persistence.
        """

        chunks = self.create_chat_completion_stream(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )
        yield from self._iter_stream_events(chunks)

    def create_chat_completion_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Call the chat completions endpoint with streaming and yield raw chunks."""

        request_kwargs = self._build_request_kwargs(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
            stream=True,
        )

        try:
            stream = self.client.chat.completions.create(**request_kwargs)
        except (APIConnectionError, APITimeoutError) as exc:
            raise LLMAPIError(f"DeepSeek stream request failed: {exc}") from exc
        except APIError as exc:
            raise LLMAPIError(f"DeepSeek stream API returned an error: {exc}") from exc

        try:
            for chunk in stream:
                yield chunk.model_dump(exclude_none=True)
        except (APIConnectionError, APITimeoutError) as exc:
            raise LLMAPIError(f"DeepSeek stream request failed while reading chunks: {exc}") from exc
        except APIError as exc:
            raise LLMAPIError(f"DeepSeek stream API returned an error while reading chunks: {exc}") from exc

    def _build_request_kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        tool_choice: str | dict[str, Any] | None,
        temperature: float | None,
        max_tokens: int | None,
        extra_body: dict[str, Any] | None,
        stream: bool,
    ) -> dict[str, Any]:
        if not messages:
            raise LLMResponseError("messages must contain at least one message.")

        request_kwargs: dict[str, Any] = {
            "model": self.config.deepseek_model,
            "messages": messages,
            "stream": stream,
        }
        if tools is not None:
            request_kwargs["tools"] = tools
        if tool_choice is not None:
            request_kwargs["tool_choice"] = tool_choice
        if temperature is not None:
            request_kwargs["temperature"] = temperature
        if max_tokens is not None:
            request_kwargs["max_tokens"] = max_tokens
        if extra_body is not None:
            request_kwargs["extra_body"] = extra_body
        return request_kwargs

    @staticmethod
    def _extract_message(response_data: dict[str, Any]) -> dict[str, Any]:
        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMResponseError("DeepSeek API response missing choices.")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise LLMResponseError("DeepSeek API choice must be an object.")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise LLMResponseError("DeepSeek API response missing assistant message.")

        if message.get("role") != "assistant":
            raise LLMResponseError("DeepSeek API message role must be assistant.")

        return message

    @staticmethod
    def _extract_stream_message(chunks: list[dict[str, Any]]) -> dict[str, Any]:
        final_message: dict[str, Any] | None = None
        for event in DeepSeekClient._iter_stream_events(chunks):
            if event["type"] == "message":
                final_message = event["message"]

        if final_message is None:
            raise LLMResponseError("DeepSeek stream response missing final message.")
        return final_message

    @staticmethod
    def _iter_stream_events(chunks: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
        role = ""
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls_by_index: dict[int, dict[str, Any]] = {}
        raw_chunks: list[dict[str, Any]] = []
        saw_chunk = False
        emitted_final_message = False

        for chunk in chunks:
            saw_chunk = True
            raw_chunks.append(chunk)

            choices = chunk.get("choices")
            if not isinstance(choices, list) or not choices:
                continue

            first_choice = choices[0]
            if not isinstance(first_choice, dict):
                raise LLMResponseError("DeepSeek stream choice must be an object.")

            delta = first_choice.get("delta") or {}
            if not isinstance(delta, dict):
                raise LLMResponseError("DeepSeek stream delta must be an object.")

            if delta.get("role"):
                role = delta["role"]

            reasoning_delta = delta.get("reasoning_content")
            if isinstance(reasoning_delta, str) and reasoning_delta:
                reasoning_parts.append(reasoning_delta)
                yield {
                    "type": "reasoning_delta",
                    "delta": reasoning_delta,
                    "chunk": chunk,
                }

            content_delta = delta.get("content")
            if isinstance(content_delta, str) and content_delta:
                content_parts.append(content_delta)
                yield {
                    "type": "content_delta",
                    "delta": content_delta,
                    "chunk": chunk,
                }

            tool_calls = delta.get("tool_calls") or []
            if not isinstance(tool_calls, list):
                raise LLMResponseError("DeepSeek stream tool_calls must be a list.")

            for tool_call_delta in tool_calls:
                index, partial_tool_call = DeepSeekClient._merge_tool_call_delta(
                    tool_calls_by_index,
                    tool_call_delta,
                )
                yield {
                    "type": "tool_call_delta",
                    "index": index,
                    "delta": deepcopy(tool_call_delta),
                    "tool_call": deepcopy(partial_tool_call),
                    "chunk": chunk,
                }

            finish_reason = first_choice.get("finish_reason")
            if finish_reason is not None:
                for tool_call in DeepSeekClient._complete_tool_calls(tool_calls_by_index):
                    yield {
                        "type": "tool_call",
                        "tool_call": deepcopy(tool_call),
                        "finish_reason": finish_reason,
                    }

                yield {
                    "type": "message",
                    "message": DeepSeekClient._build_stream_message(
                        role=role,
                        content_parts=content_parts,
                        reasoning_parts=reasoning_parts,
                        tool_calls_by_index=tool_calls_by_index,
                        raw_chunks=raw_chunks,
                    ),
                    "finish_reason": finish_reason,
                }
                emitted_final_message = True

        if not saw_chunk:
            raise LLMResponseError("DeepSeek stream response missing chunks.")

        if not emitted_final_message:
            for tool_call in DeepSeekClient._complete_tool_calls(tool_calls_by_index):
                yield {
                    "type": "tool_call",
                    "tool_call": deepcopy(tool_call),
                    "finish_reason": None,
                }
            yield {
                "type": "message",
                "message": DeepSeekClient._build_stream_message(
                    role=role,
                    content_parts=content_parts,
                    reasoning_parts=reasoning_parts,
                    tool_calls_by_index=tool_calls_by_index,
                    raw_chunks=raw_chunks,
                ),
                "finish_reason": None,
            }

    @staticmethod
    def _merge_tool_call_delta(
        tool_calls_by_index: dict[int, dict[str, Any]],
        tool_call_delta: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        if not isinstance(tool_call_delta, dict):
            raise LLMResponseError("DeepSeek stream tool_call delta must be an object.")

        index = tool_call_delta.get("index")
        if not isinstance(index, int):
            index = len(tool_calls_by_index)

        tool_call = tool_calls_by_index.setdefault(
            index,
            {
                "index": index,
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            },
        )

        if tool_call_delta.get("id"):
            tool_call["id"] = tool_call_delta["id"]
        if tool_call_delta.get("type"):
            tool_call["type"] = tool_call_delta["type"]

        function_delta = tool_call_delta.get("function") or {}
        if not isinstance(function_delta, dict):
            raise LLMResponseError("DeepSeek stream tool_call function delta must be an object.")

        function = tool_call.setdefault("function", {"name": "", "arguments": ""})
        if function_delta.get("name"):
            function["name"] += function_delta["name"]
        if function_delta.get("arguments"):
            function["arguments"] += function_delta["arguments"]

        return index, tool_call

    @staticmethod
    def _complete_tool_calls(tool_calls_by_index: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        return [tool_calls_by_index[index] for index in sorted(tool_calls_by_index)]

    @staticmethod
    def _build_stream_message(
        role: str,
        content_parts: list[str],
        reasoning_parts: list[str],
        tool_calls_by_index: dict[int, dict[str, Any]],
        raw_chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not role:
            role = "assistant"
        if role != "assistant":
            raise LLMResponseError("DeepSeek stream message role must be assistant.")

        message: dict[str, Any] = {
            "role": role,
            "content": "".join(content_parts),
            "reasoning_content": "".join(reasoning_parts),
        }
        tool_calls = DeepSeekClient._complete_tool_calls(tool_calls_by_index)
        if tool_calls:
            message["tool_calls"] = tool_calls
        message["_stream_chunks"] = raw_chunks
        return message
