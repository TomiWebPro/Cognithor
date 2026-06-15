from __future__ import annotations
import datetime
import random
import time
from typing import Optional

from log_service import LogService

from secure_db_service import SecureDbService

from .config import EndpointSettings
from log_service.database import LogDatabase

from .database import Tracker
from .models import EndpointStatus, Message, ProviderRecord
from .providers import HttpProvider, UsageInfo


class EndpointManager:
    def __init__(
        self,
        tracker: Optional[Tracker] = None,
        settings: Optional[EndpointSettings] = None,
        log_service: Optional[LogService] = None,
        svc: Optional[SecureDbService] = None,
    ):
        self.tracker = tracker or Tracker(svc=svc)
        if log_service is not None:
            self.log = log_service
        elif svc is not None:
            self.log = LogService(
                database=LogDatabase(use_encryption=svc.use_encryption),
            )
        else:
            self.log = LogService()
        self.settings = settings or EndpointSettings(
            tracker=self.tracker, log_service=self.log,
        )
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
            agent_id=context,
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
            _, usage = instance.chat(
                [Message(role="user", content="hello")],
                max_tokens=1,
            )
            status.latency_ms = (time.perf_counter() - start) * 1000
            status.available = usage.output_tokens == 1
            if status.available:
                self.log.normal_operation(
                    f"Health check passed provider={name} latency={status.latency_ms:.0f}ms",
                    folder="endpoint", file=__file__,
                )
            else:
                status.error = f"Expected 1 token, got {usage.output_tokens}"
        except Exception as exc:
            status.available = False
            status.error = str(exc)
            self.log.warning(
                f"Health check failed provider={name}: {exc}",
                folder="endpoint", file=__file__,
            )
        status.last_checked = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return status

    def test_model(self, name: str, model_name: str) -> dict:
        record = self.tracker.get_provider(name)
        if record is None:
            raise ValueError(f"Unknown provider: {name}")
        if model_name not in record.models:
            raise ValueError(f"Model '{model_name}' not found in provider '{name}'")

        instance = self._get_provider_instance(name)
        start = time.perf_counter()
        try:
            _, usage = instance.chat(
                [Message(role="user", content="hello")],
                model=model_name,
                max_tokens=1,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            passed = usage.output_tokens == 1
            result = {"available": passed, "latency_ms": latency_ms, "output_tokens": usage.output_tokens}
            if not passed:
                result["error"] = f"Expected 1 token, got {usage.output_tokens}"
        except Exception as exc:
            result = {"available": False, "latency_ms": None, "output_tokens": 0, "error": str(exc)}

        record.active_models[model_name] = result["available"]
        any_active = any(record.active_models.values())
        record.is_active = any_active
        self.tracker.save_provider(record)
        self._instances.pop(name, None)

        result["last_checked"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return result

    def check_all(self) -> list[EndpointStatus]:
        return [self.check_status(p.name) for p in self.tracker.list_providers()]

    def register_provider(self, record: ProviderRecord) -> None:
        self.tracker.save_provider(record)
        self._instances.pop(record.name, None)
        self.log.notify(
            f"Provider registered: {record.name}",
            folder="endpoint", file=__file__,
        )

    def delete_provider(self, name: str) -> bool:
        try:
            if not self.tracker.delete_provider(name):
                return False
            self._instances.pop(name, None)
            self.log.notify(
                f"Provider deleted: {name}",
                folder="endpoint", file=__file__,
            )
            return True
        except Exception as exc:
            self.log.error(
                f"Failed to delete provider {name}: {exc}",
                folder="endpoint", file=__file__,
            )
            return False
