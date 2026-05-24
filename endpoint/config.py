from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Optional

from log_service import LogService

from .database import Tracker
from .models import ProviderRecord


ENDPOINT_VAR_PREFIX = "COGNITHOR_"
DEFAULT_CONFIG_PATH = Path("endpoint_config.json")


class EndpointSettings:
    def __init__(
        self,
        tracker: Optional[Tracker] = None,
        config_path: Optional[Path] = None,
        log_service: Optional[LogService] = None,
    ):
        self.log = log_service or LogService()
        self.tracker = tracker or Tracker()
        self._load_from_env()
        self._load_from_file(config_path or DEFAULT_CONFIG_PATH)

    def _load_from_env(self) -> None:
        known_fields = {
            "_api_key": "api_key",
            "_base_url": "base_url",
        }
        for key, val in os.environ.items():
            if not key.startswith(ENDPOINT_VAR_PREFIX):
                continue
            suffix = key[len(ENDPOINT_VAR_PREFIX):].lower()
            if suffix == "active_provider":
                self.log.notify(
                    f"active_provider env var ignored (activation is now test-driven): {val.lower()}",
                    folder="endpoint", file=__file__,
                )
                continue

            field = None
            provider_name = None
            for sfx, fname in known_fields.items():
                if suffix.endswith(sfx):
                    provider_name = suffix[:-len(sfx)]
                    field = fname
                    break
            if field is None or not provider_name:
                continue

            rec = self.tracker.get_provider(provider_name)
            if rec is None:
                rec = ProviderRecord(name=provider_name, base_url="")

            if field == "api_key":
                rec.api_key = val
            elif field == "base_url":
                rec.base_url = val

            self.tracker.save_provider(rec)

    def _load_from_file(self, path: Path) -> None:
        if not path.exists():
            self.log.normal_operation(
                f"Config file not found at {path}, skipping", folder="endpoint", file=__file__,
            )
            return
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            self.log.warning(
                f"Failed to parse config file {path}: {exc}",
                folder="endpoint", file=__file__,
            )
            return
        except OSError as exc:
            self.log.warning(
                f"Failed to read config file {path}: {exc}",
                folder="endpoint", file=__file__,
            )
            return

        for provider_name, opts in data.get("endpoints", {}).items():
            rec = self.tracker.get_provider(provider_name)
            if rec is None:
                rec = ProviderRecord(name=provider_name, base_url=opts.get("base_url", ""))
            if opts.get("api_key"):
                rec.api_key = opts["api_key"]
            if opts.get("base_url"):
                rec.base_url = opts["base_url"]
            if opts.get("models"):
                raw = opts["models"]
                if isinstance(raw, list):
                    rec.models = {m: m for m in raw}
                else:
                    rec.models = raw
            if opts.get("headers_template"):
                rec.headers_template = opts["headers_template"]
            if opts.get("auth_type"):
                rec.auth_type = opts["auth_type"]
            if opts.get("body_template"):
                rec.body_template = opts["body_template"]
            if opts.get("endpoint_path"):
                rec.endpoint_path = opts["endpoint_path"]
            if opts.get("response_content_path"):
                rec.response_content_path = opts["response_content_path"]
            if opts.get("response_usage_input_path"):
                rec.response_usage_input_path = opts["response_usage_input_path"]
            if opts.get("response_usage_output_path"):
                rec.response_usage_output_path = opts["response_usage_output_path"]
            if opts.get("is_streaming"):
                rec.is_streaming = opts["is_streaming"]
            rec.max_retries = opts.get("max_retries", rec.max_retries)
            rec.timeout_seconds = opts.get("timeout_seconds", rec.timeout_seconds)
            rec.max_concurrent = opts.get("max_concurrent", rec.max_concurrent)
            self.tracker.save_provider(rec)

        active = data.get("active_provider")
        if active:
            self.log.notify(
                f"Active provider '{active}' from config file ignored (activation is now test-driven)",
                folder="endpoint", file=__file__,
            )
