from __future__ import annotations
import datetime
import random
import time
from typing import Optional

from log_service import LogService

from .config import EndpointSettings
from .database import Tracker
from .models import EndpointStatus, Message, ProviderRecord
from .providers import HttpProvider, UsageInfo


class EndpointManager:
    def __init__(
        self,
        tracker: Optional[Tracker] = None,
        settings: Optional[EndpointSettings] = None,
        log_service: Optional[LogService] = None,
    ):
        self.tracker = tracker or Tracker()
        self.settings = settings or EndpointSettings(tracker=self.tracker)
        self.log = log_service or LogService()
        self._instances: dict[str, HttpProvider] = {}

    def _get_provider_instance(self, name: str) -> HttpProvider:
        if name not in self._instances:
            record = self.tracker.get_provider(name)
            if record is None:
                raise ValueError(f"Unknown provider: {name}")
            self._instances[name] = HttpProvider(record)
        return self._instances[name]

    def chat(
        self,
        messages: list[Message],
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        context: Optional[str] = None,
    ) -> tuple[str, UsageInfo]:
        if provider is None:
            active = self.tracker.get_active_provider()
            if active is None:
                all_providers = self.tracker.list_providers()
                if not all_providers:
                    self.log.error("No provider configured", folder="endpoint")
                    raise RuntimeError("No provider configured")
                provider = all_providers[0].name
            else:
                provider = active.name

        instance = self._get_provider_instance(provider)
        try:
            content, usage = instance.chat(messages, model, temperature, max_tokens)
        except Exception as exc:
            self.log.log_exception(
                exc, folder="endpoint", file=__file__,
                message=f"Chat failed for provider={provider} model={model}",
            )
            raise

        self.tracker.record_usage(
            provider=provider,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost=usage.cost,
            duration_ms=usage.duration_ms,
            status="completed",
            context=context,
        )
        self.log.normal_operation(
            f"Chat completed provider={provider} model={usage.model} tokens_in={usage.input_tokens} tokens_out={usage.output_tokens}",
            folder="endpoint", file=__file__,
        )
        return content, usage

    def chat_with_fallback(
        self,
        messages: list[Message],
        preferred: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        context: Optional[str] = None,
    ) -> tuple[str, UsageInfo, str]:
        providers = [p.name for p in self.tracker.list_providers()]
        if not providers:
            raise RuntimeError("No provider configured")

        ordered = []
        if preferred:
            ordered.append(preferred)
        ordered.extend(p for p in providers if p != preferred)

        last_error = None
        for name in ordered:
            try:
                content, usage = self.chat(messages, name, model, temperature, max_tokens, context)
                self.log.notify(
                    f"Fallback succeeded with {name}",
                    folder="endpoint", file=__file__,
                )
                return content, usage, name
            except Exception as exc:
                self.log.warning(
                    f"Fallback provider={name} failed: {exc}",
                    folder="endpoint", file=__file__,
                )
                last_error = exc
                continue

        self.log.error(
            f"All providers failed. Last error: {last_error}",
            folder="endpoint", file=__file__,
        )
        raise RuntimeError(f"All providers failed. Last error: {last_error}")

    def chat_with_round_robin(
        self,
        messages: list[Message],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        context: Optional[str] = None,
    ) -> tuple[str, UsageInfo, str]:
        providers = [p.name for p in self.tracker.list_providers()]
        if not providers:
            self.log.error("No provider configured for round-robin", folder="endpoint", file=__file__)
            raise RuntimeError("No provider configured")
        name = random.choice(providers)
        self.log.normal_operation(
            f"Round-robin selected provider={name}",
            folder="endpoint", file=__file__,
        )
        content, usage = self.chat(messages, name, model, temperature, max_tokens, context)
        return content, usage, name

    def check_status(self, name: str) -> EndpointStatus:
        status = EndpointStatus(provider=name)
        try:
            instance = self._get_provider_instance(name)
            start = time.perf_counter()
            instance.chat(
                [Message(role="user", content="Respond with only the word: ok")],
                max_tokens=10,
            )
            status.latency_ms = (time.perf_counter() - start) * 1000
            status.available = True
            self.log.normal_operation(
                f"Health check passed provider={name} latency={status.latency_ms:.0f}ms",
                folder="endpoint", file=__file__,
            )
        except Exception as exc:
            status.available = False
            status.error = str(exc)
            self.log.warning(
                f"Health check failed provider={name}: {exc}",
                folder="endpoint", file=__file__,
            )
        status.last_checked = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return status

    def check_all(self) -> list[EndpointStatus]:
        return [self.check_status(p.name) for p in self.tracker.list_providers()]

    def register_provider(self, record: ProviderRecord) -> None:
        self.tracker.save_provider(record)
        self._instances.pop(record.name, None)
        self.log.notify(
            f"Provider registered: {record.name}",
            folder="endpoint", file=__file__,
        )
