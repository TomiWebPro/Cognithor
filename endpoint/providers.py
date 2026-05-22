from __future__ import annotations
import json
import time
from string import Template
from typing import TYPE_CHECKING, Optional

from log_service import LogService

from .models import Message, ProviderRecord

if TYPE_CHECKING:
    import httpx


class UsageInfo:
    def __init__(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost: float = 0.0,
        duration_ms: float = 0.0,
        model: str = "",
    ):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost = cost
        self.duration_ms = duration_ms
        self.model = model


def _navigate(obj, path: str):
    if not path:
        return None
    parts = path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, (list, tuple)):
            try:
                idx = int(part)
                current = current[idx] if 0 <= idx < len(current) else None
            except (ValueError, IndexError):
                return None
        else:
            return None
        if current is None:
            return None
    return current


def _prepare_messages(
    messages: list[Message], body_template: str
) -> tuple[str, str]:
    has_system = "${system_prompt}" in body_template
    system_prompt = ""
    api_messages = []

    if has_system:
        for m in messages:
            if m.role == "system" and not system_prompt:
                system_prompt = m.content
            else:
                api_messages.append({"role": m.role, "content": m.content})
    else:
        api_messages = [{"role": m.role, "content": m.content} for m in messages]

    messages_json = json.dumps(api_messages, ensure_ascii=False)
    return messages_json, system_prompt


class HttpProvider:
    def __init__(self, record: ProviderRecord, log_service: Optional[LogService] = None):
        self.record = record
        self.log = log_service or LogService()

    def chat(
        self,
        messages: list[Message],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> tuple[str, UsageInfo]:
        model = model or self.record.get_model("high")
        if not model:
            model = self.record.default_model or ""
        if not max_tokens:
            max_tokens = 4096

        messages_json, system_prompt = _prepare_messages(messages, self.record.body_template)

        substitutions = {
            "model": model,
            "messages_json": messages_json,
            "temperature": str(temperature),
            "max_tokens": str(max_tokens),
            "system_prompt": system_prompt,
        }
        body_str = Template(self.record.body_template).substitute(substitutions)

        try:
            body = json.loads(body_str)
        except json.JSONDecodeError as exc:
            self.log.error(
                f"Failed to parse body template for provider={self.record.name}: {exc}",
                folder="endpoint/providers", file=__file__,
            )
            raise

        client = self._build_client()
        url = self.record.endpoint_path

        headers = dict(self.record.headers_template)
        headers["Content-Type"] = "application/json"

        if self.record.auth_type == "bearer":
            headers["Authorization"] = f"Bearer {self.record.api_key}"
        elif self.record.auth_type == "header":
            header_name = self.record.auth_header_name or "x-api-key"
            headers[header_name] = self.record.api_key or ""

        start = time.perf_counter()
        try:
            resp = client.post(url, json=body, headers=headers)
            resp.raise_for_status()
        except Exception as exc:
            self.log.error(
                f"HTTP request failed provider={self.record.name} url={url}: {exc}",
                folder="endpoint/providers", file=__file__,
            )
            raise
        elapsed = (time.perf_counter() - start) * 1000

        if self.record.is_streaming:
            content, usage_data = self._parse_streaming(resp)
        else:
            try:
                data = resp.json()
            except json.JSONDecodeError as exc:
                self.log.error(
                    f"Failed to parse JSON response provider={self.record.name}: {exc}",
                    folder="endpoint/providers", file=__file__,
                )
                raise
            content, usage_data = self._parse_json(data)

        info = UsageInfo(
            input_tokens=int(_navigate(usage_data, self.record.response_usage_input_path) or 0),
            output_tokens=int(_navigate(usage_data, self.record.response_usage_output_path) or 0),
            duration_ms=elapsed,
            model=model,
        )
        if self.record.response_usage_cost_path:
            info.cost = float(_navigate(usage_data, self.record.response_usage_cost_path) or 0.0)

        return content, info

    def _build_client(self):
        import httpx
        timeout = httpx.Timeout(self.record.timeout_seconds)
        return httpx.Client(base_url=self.record.base_url, timeout=timeout)

    def _parse_json(self, data: dict) -> tuple[str, dict]:
        content = _navigate(data, self.record.response_content_path) or ""
        usage_data = data
        if self.record.response_usage_input_path or self.record.response_usage_output_path:
            usage_path = self.record.response_usage_input_path or self.record.response_usage_output_path
            top_key = usage_path.split(".")[0] if usage_path else None
            if top_key and top_key in data:
                usage_data = data
        return str(content), usage_data

    def _parse_streaming(self, resp) -> tuple[str, dict]:
        content_parts = []
        usage_data: dict = {}
        for line in resp.text.strip().split("\n"):
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            content_part = _navigate(chunk, self.record.response_content_path)
            if content_part:
                content_parts.append(str(content_part))
            if self.record.response_usage_output_path:
                val = _navigate(chunk, self.record.response_usage_output_path)
                if val is not None:
                    usage_data[self.record.response_usage_output_path] = val
        return "".join(content_parts), usage_data
