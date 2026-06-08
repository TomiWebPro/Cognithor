from __future__ import annotations

import json
import logging
from typing import Optional

from agents_service import AgentManager, parse_model_ref
from core.app.app_manager import AppTabManager
from core.past_action.past_actions import PastActionsService
from endpoint import EndpointManager, Message

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
    ):
        self.app_tab_mgr = app_tab_mgr
        self.endpoint_mgr = endpoint_mgr
        self.agent_mgr = agent_mgr
        self.past_actions_svc = past_actions_svc
        self.notes_handler = notes_handler
        self.diary_svc = diary_svc

    def run(
        self,
        agent_id: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        agent = self.agent_mgr.get_agent(agent_id)
        if agent is None:
            raise ValueError(f"Agent not found: {agent_id}")

        self.app_tab_mgr.refresh_interfaces(agent_id)
        ctx = self.app_tab_mgr.get_agent_context(
            agent_id,
            max_past_actions=agent.max_past_actions or 15,
            show_context_window=agent.show_context_window,
            context_window=agent.context_window or 4096,
            agent_can_change_max_past_actions=agent.agent_can_change_max_past_actions,
            show_notes=getattr(agent, "show_notes", True),
            show_diary=getattr(agent, "show_diary", True),
        )

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

        if self.past_actions_svc is not None:
            self.past_actions_svc.record_action(agent_id, "assistant", response)
            self.past_actions_svc.trim_actions(agent_id, agent.max_past_actions or 15)

        return response

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

    def _handle_notes_diary_commands(self, response: str, agent, agent_id: str) -> str:
        import re as _re

        notes_pattern = _re.compile(
            r'\{"command"\s*:\s*"write_note"\s*,\s*"content"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
        )
        match = notes_pattern.search(response)
        if match and self.notes_handler is not None:
            content = match.group(1)
            self.notes_handler.execute({"agent_id": agent_id, "content": content})
            logger.info("Agent %s wrote notes via command", agent_id)
            stripped = response[:match.start()].rstrip() + response[match.end():]
            stripped = stripped.strip()
            response = stripped if stripped else response

        extend_pattern = _re.compile(
            r'\{"command"\s*:\s*"extend_note"\s*,\s*"max_interactions"\s*:\s*(\d+)\s*\}'
        )
        match = extend_pattern.search(response)
        if match and self.notes_handler is not None:
            max_int = int(match.group(1))
            self.notes_handler.extend_note(agent_id, max_interactions=max_int)
            logger.info("Agent %s extended note to %d max interactions", agent_id, max_int)
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
