from __future__ import annotations

import json
import logging
from typing import Optional

from agents_service import AgentManager, parse_model_ref
from core.app.app_manager import AppTabManager
from core.past_action.past_actions import PastActionsService
from endpoint import EndpointManager, Message
from apps_service import AgentAppManager

logger = logging.getLogger(__name__)


class AgentRunner:
    def __init__(
        self,
        app_tab_mgr: AppTabManager,
        endpoint_mgr: EndpointManager,
        agent_mgr: AgentManager,
        past_actions_svc: Optional[PastActionsService] = None,
        notes_handler: Optional = None,
        diary_svc: Optional = None,
        notes_manager: Optional = None,
        alarm_svc: Optional = None,
        agent_app_mgr: Optional[AgentAppManager] = None,
    ):
        self.app_tab_mgr = app_tab_mgr
        self.endpoint_mgr = endpoint_mgr
        self.agent_mgr = agent_mgr
        self.past_actions_svc = past_actions_svc
        self.notes_handler = notes_handler
        self.diary_svc = diary_svc
        self.notes_manager = notes_manager
        self.alarm_svc = alarm_svc
        self.agent_app_mgr = agent_app_mgr

    def run(
        self,
        agent_id: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> dict:
        agent = self.agent_mgr.get_agent(agent_id)
        if agent is None:
            raise ValueError(f"Agent not found: {agent_id}")

        triggered_alarms = []
        if self.alarm_svc is not None:
            fresh = self.alarm_svc.check_alarms(agent_id)
            previous = self.alarm_svc.get_triggered_alarms(agent_id)
            seen = set()
            for a in fresh + previous:
                if a["id"] not in seen:
                    seen.add(a["id"])
                    triggered_alarms.append(a)

        alarm_notification = ""
        if triggered_alarms:
            alarm_lines = ["[Alarm Ringing!]"]
            for a in triggered_alarms:
                msg = a.get("message", "") or "(no message)"
                alarm_lines.append(f"  {msg} (id={a['id']})")
            alarm_lines.append('  Acknowledge: {"command": "acknowledge_alarm", "alarm_id": "..."}')
            alarm_lines.append("")
            alarm_notification = "\n".join(alarm_lines)

        self.app_tab_mgr.refresh_interfaces(agent_id)
        ctx = self.app_tab_mgr.get_agent_context(
            agent_id,
            max_past_actions=agent.max_past_actions or 15,
            show_context_window=agent.show_context_window,
            context_window=agent.context_window or 4096,
            agent_can_change_max_past_actions=agent.agent_can_change_max_past_actions,
            show_notes=getattr(agent, "show_notes", True),
            show_diary=getattr(agent, "show_diary", True),
            show_time=getattr(agent, "show_time", True),
            notes_manager=self.notes_manager,
        )

        if alarm_notification:
            ctx = alarm_notification + "\n\n" + ctx if ctx else alarm_notification

        agent_info = json.dumps({
            "type": "session",
            "agent": {
                "name": agent.name,
                "agent_id": agent.agent_id,
                "context_window": agent.context_window,
                "max_past_actions": agent.max_past_actions or 15,
                "agent_can_change_max_past_actions": agent.agent_can_change_max_past_actions,
            },
        }, indent=2)

        context_text = agent_info + ("\n\n" + ctx if ctx else "")

        if system_prompt:
            content = system_prompt + "\n\n" + context_text
        else:
            content = context_text

        messages = [Message(role="user", content=content)]

        provider = None
        model = None
        if agent.model_ref:
            try:
                provider, model = parse_model_ref(agent.model_ref)
            except Exception:
                logger.error("Failed to parse model_ref '%s', falling back to default provider", agent.model_ref, exc_info=True)

        response, _ = self.endpoint_mgr.chat(
            messages=messages,
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            context=agent_id,
        )

        response = self._handle_config_command(response, agent)
        response = self._handle_notes_diary_commands(response, agent, agent_id)
        response, wait_seconds = self._handle_alarm_wait_commands(response, agent, agent_id)
        response = self._handle_app_commands(response, agent_id)

        if self.past_actions_svc is not None:
            self.past_actions_svc.record_action(agent_id, "assistant", response)
            self.past_actions_svc.trim_actions(agent_id, agent.max_past_actions or 15)

        result = {"response": response}
        if wait_seconds is not None:
            result["wait"] = wait_seconds
        return result

    def _handle_config_command(self, response: str, agent) -> str:
        import re as _re
        match = _re.search(r'\{"command"\s*:\s*"config"\s*,\s*"max_past_actions"\s*:\s*(\d+)\s*\}', response)
        if not match:
            match = _re.search(r"\{\s*'command'\s*:\s*'config'\s*,\s*'max_past_actions'\s*:\s*(\d+)\s*\}", response)
        if not match:
            return response

        new_val = int(match.group(1))
        if new_val < 3:
            logger.warning("Config command rejected: max_past_actions %d is below minimum 3", new_val)
            return response
        if not getattr(agent, "agent_can_change_max_past_actions", False):
            logger.warning("Config command rejected: agent not allowed to change max_past_actions")
            return response

        self.agent_mgr.update_agent(agent.agent_id, max_past_actions=new_val)
        agent.max_past_actions = new_val
        logger.info("Agent %s updated max_past_actions to %d via config command", agent.agent_id, new_val)

        stripped = response[:match.start()].rstrip() + response[match.end():]
        stripped = stripped.strip()
        return stripped if stripped else response

    def _find_note_tab(self, agent_id: str, note_id: str):
        import json as _json
        for rec in self.app_tab_mgr.list_open_apps(agent_id):
            if rec.app_id == "__note__":
                params = _json.loads(rec.params) if rec.params else {}
                if params.get("note_id") == note_id:
                    return rec
        return None

    def _handle_notes_diary_commands(self, response: str, agent, agent_id: str) -> str:
        import re as _re
        import json as _json

        notes_mgr = getattr(self, "notes_manager", self.notes_handler)

        create_pattern = _re.compile(
            r'\{"command"\s*:\s*"create_note"\s*,\s*"title"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"content"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
        )
        match = create_pattern.search(response)
        if match and notes_mgr is not None:
            title = match.group(1)
            content = match.group(2)
            note_id = notes_mgr.create_note(agent_id, title=title, content=content)
            self.app_tab_mgr.open_app(
                agent_id, "__note__",
                tab_label=title or "untitled",
                params={"note_id": note_id, "agent_id": agent_id},
                is_persistent=False,
            )
            logger.info("Agent %s created note %s", agent_id, note_id)
            stripped = response[:match.start()].rstrip() + response[match.end():]
            stripped = stripped.strip()
            response = stripped if stripped else response

        write_pattern = _re.compile(
            r'\{"command"\s*:\s*"edit_note"\s*,\s*"note_id"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"content"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
        )
        match = write_pattern.search(response)
        if match and notes_mgr is not None:
            note_id = match.group(1)
            content = match.group(2)
            notes_mgr.update_note(note_id, content=content)
            tab = self._find_note_tab(agent_id, note_id)
            if tab:
                self.app_tab_mgr.refresh_interface(tab.id)
            logger.info("Agent %s wrote to note %s", agent_id, note_id)
            stripped = response[:match.start()].rstrip() + response[match.end():]
            stripped = stripped.strip()
            response = stripped if stripped else response

        extend_pattern = _re.compile(
            r'\{"command"\s*:\s*"reset_note_lifetime"\s*,\s*"note_id"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"max_interactions"\s*:\s*(\d+)\s*\}'
        )
        match = extend_pattern.search(response)
        if match and notes_mgr is not None:
            note_id = match.group(1)
            max_int = int(match.group(2))
            notes_mgr.extend_note(note_id, max_interactions=max_int)
            tab = self._find_note_tab(agent_id, note_id)
            if tab:
                self.app_tab_mgr.refresh_interface(tab.id)
            logger.info("Agent %s extended note %s to %d max interactions", agent_id, note_id, max_int)
            stripped = response[:match.start()].rstrip() + response[match.end():]
            stripped = stripped.strip()
            response = stripped if stripped else response

        delete_pattern = _re.compile(
            r'\{"command"\s*:\s*"delete_note"\s*,\s*"note_id"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
        )
        match = delete_pattern.search(response)
        if match and notes_mgr is not None:
            note_id = match.group(1)
            notes_mgr.delete_note(note_id)
            tab = self._find_note_tab(agent_id, note_id)
            if tab:
                try:
                    self.app_tab_mgr.close_tab(tab.id)
                except ValueError:
                    pass
            logger.info("Agent %s deleted note %s", agent_id, note_id)
            stripped = response[:match.start()].rstrip() + response[match.end():]
            stripped = stripped.strip()
            response = stripped if stripped else response

        diary_pattern = _re.compile(
            r'\{"command"\s*:\s*"write_diary"\s*,\s*"content"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
        )
        match = diary_pattern.search(response)
        if match and self.diary_svc is not None:
            content = match.group(1)
            from core.time import TimeService
            time_svc = getattr(self, "_time_svc", None)
            self.diary_svc.append_diary(agent_id, content, time_svc=time_svc)
            logger.info("Agent %s wrote diary entry", agent_id)
            stripped = response[:match.start()].rstrip() + response[match.end():]
            stripped = stripped.strip()
            response = stripped if stripped else response

        return response

    def _handle_alarm_wait_commands(self, response: str, agent, agent_id: str) -> tuple[str, Optional[float]]:
        import re as _re
        import datetime as _datetime

        wait_seconds = None

        set_alarm_pattern = _re.compile(
            r'\{"command"\s*:\s*"set_alarm"\s*,\s*"time"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"message"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
        )
        match = set_alarm_pattern.search(response)
        if match and self.alarm_svc is not None:
            alarm_time = match.group(1)
            message = match.group(2)
            time_type = "agent"
            type_match = _re.search(r'"time_type"\s*:\s*"(agent|real)"', response)
            if type_match:
                time_type = type_match.group(1)
            result = self.alarm_svc.set_alarm(agent_id, alarm_time, time_type=time_type, message=message)
            if result:
                logger.info("Agent %s set alarm %s at %s (%s): %s", agent_id, result, alarm_time, time_type, message)
            else:
                logger.warning("Agent %s attempted to set alarm in the past: %s", agent_id, alarm_time)
            stripped = response[:match.start()].rstrip() + response[match.end():]
            stripped = stripped.strip()
            response = stripped if stripped else response

        acknowledge_pattern = _re.compile(
            r'\{"command"\s*:\s*"acknowledge_alarm"\s*,\s*"alarm_id"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
        )
        match = acknowledge_pattern.search(response)
        if match and self.alarm_svc is not None:
            alarm_id = match.group(1)
            if self.alarm_svc.acknowledge_alarm(alarm_id):
                logger.info("Agent %s acknowledged alarm %s", agent_id, alarm_id)
            stripped = response[:match.start()].rstrip() + response[match.end():]
            stripped = stripped.strip()
            response = stripped if stripped else response

        wait_pattern = _re.compile(
            r'\{"command"\s*:\s*"wait"\s*,\s*"duration"\s*:\s*(\d+(?:\.\d+)?)\s*\}'
        )
        match = wait_pattern.search(response)
        if match:
            wait_seconds = float(match.group(1))
            stripped = response[:match.start()].rstrip() + response[match.end():]
            stripped = stripped.strip()
            response = stripped if stripped else response
            logger.info("Agent %s requested wait of %.1f seconds", agent_id, wait_seconds)

        wait_until_pattern = _re.compile(
            r'\{"command"\s*:\s*"wait_until"\s*,\s*"time"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
        )
        match = wait_until_pattern.search(response)
        if match:
            target_str = match.group(1)
            try:
                target_dt = _datetime.datetime.fromisoformat(target_str)
                now = _datetime.datetime.now(_datetime.timezone.utc)
                if target_dt.tzinfo is None:
                    target_dt = target_dt.replace(tzinfo=_datetime.timezone.utc)
                diff = (target_dt - now).total_seconds()
                if diff > 0:
                    wait_seconds = diff
            except Exception:
                logger.warning("Agent %s sent invalid wait_until time: %s", agent_id, target_str)
            stripped = response[:match.start()].rstrip() + response[match.end():]
            stripped = stripped.strip()
            response = stripped if stripped else response

        return response, wait_seconds

    @staticmethod
    def _parse_json_block(text: str, start: int) -> tuple[dict, int]:
        depth = 0
        in_string = False
        escape = False
        i = start
        while i < len(text):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == '\\':
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        block = text[start:i + 1]
                        return json.loads(block), i + 1
                elif ch == '"':
                    in_string = True
            i += 1
        raise ValueError("Unmatched opening brace")

    def _handle_app_commands(self, response: str, agent_id: str) -> str:
        blocks = []
        i = 0
        while i < len(response):
            brace_pos = response.find('{', i)
            if brace_pos == -1:
                break
            try:
                cmd_obj, end = self._parse_json_block(response, brace_pos)
                command = cmd_obj.get("command", "").lower()
                if command in ("execute", "run", "open_app", "close_tab"):
                    blocks.append((cmd_obj, brace_pos, end, command))
                i = end
            except (ValueError, json.JSONDecodeError):
                i = brace_pos + 1

        if not blocks:
            return response

        for cmd_obj, start, end, command in reversed(blocks):
            if command in ("execute", "run"):
                self._do_execute(cmd_obj, agent_id)
            elif command == "open_app":
                self._do_open_app(cmd_obj, agent_id)
            elif command == "close_tab":
                self._do_close_tab(cmd_obj, agent_id)
            response = response[:start] + response[end:]

        return response.strip()

    def _do_execute(self, cmd: dict, agent_id: str) -> None:
        app_id = cmd.get("app_id", "")
        action = cmd.get("action", cmd.get("params", {}))
        if not isinstance(action, dict):
            action = {}

        action.setdefault("agent_id", agent_id)
        tab_label = cmd.get("tab_label")
        if tab_label:
            action.setdefault("_tab_label", tab_label)

        if self.agent_app_mgr is not None:
            record = self.agent_app_mgr.get_agent_app(agent_id, app_id)
            if record is None or not record.is_enabled:
                logger.warning("Agent %s tried to execute uninstalled/disabled app '%s'", agent_id, app_id)
                return
            if record.config:
                try:
                    config = json.loads(record.config)
                    action.setdefault("_app_config", config)
                except (json.JSONDecodeError, TypeError):
                    pass

        handler = self.app_tab_mgr._handlers.get(app_id)
        if handler is None:
            logger.warning("No handler for app '%s'", app_id)
            return

        result = handler.execute(action)
        self.app_tab_mgr.process_tab_operations(result, agent_id)
        if self.past_actions_svc is not None:
            summary = result.get("past_action_summary")
            self.past_actions_svc.record_action(
                agent_id, "assistant", json.dumps(result),
                app_id=app_id, summary=summary,
            )
        logger.info("Agent %s executed app '%s'", agent_id, app_id)

    def _do_open_app(self, cmd: dict, agent_id: str) -> None:
        app_id = cmd.get("app_id", "")
        params = cmd.get("params")
        tab_label = cmd.get("tab_label")

        try:
            tab_id, interface = self.app_tab_mgr.open_app(
                agent_id=agent_id,
                app_id=app_id,
                tab_label=tab_label,
                params=params,
            )
            if self.past_actions_svc is not None:
                self.past_actions_svc.record_action(
                    agent_id, "assistant",
                    json.dumps({"tab_id": tab_id, "app_id": app_id, "status": "opened"}),
                    app_id=app_id,
                )
            logger.info("Agent %s opened app '%s' (tab %s)", agent_id, app_id, tab_id)
        except ValueError as e:
            logger.warning("Agent %s failed to open app '%s': %s", agent_id, app_id, e)

    def _do_close_tab(self, cmd: dict, agent_id: str) -> None:
        tab_id = cmd.get("tab_id", "")
        if not tab_id:
            logger.warning("Agent %s sent close_tab without tab_id", agent_id)
            return
        try:
            self.app_tab_mgr.close_tab(tab_id)
            logger.info("Agent %s closed tab %s", agent_id, tab_id)
        except ValueError as e:
            logger.warning("Agent %s failed to close tab %s: %s", agent_id, tab_id, e)
