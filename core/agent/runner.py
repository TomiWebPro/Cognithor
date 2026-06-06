from __future__ import annotations

import json
from typing import Optional

from agents_service import AgentManager, parse_model_ref
from core.app_manager import AppTabManager
from core.past_actions import PastActionsService
from endpoint import EndpointManager, Message


class AgentRunner:
    def __init__(
        self,
        app_tab_mgr: AppTabManager,
        endpoint_mgr: EndpointManager,
        agent_mgr: AgentManager,
        past_actions_svc: Optional[PastActionsService] = None,
    ):
        self.app_tab_mgr = app_tab_mgr
        self.endpoint_mgr = endpoint_mgr
        self.agent_mgr = agent_mgr
        self.past_actions_svc = past_actions_svc

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
            past_actions_svc=self.past_actions_svc,
            max_past_actions=agent.max_past_actions or 15,
        )

        agent_info = json.dumps({
            "type": "session",
            "agent": {
                "name": agent.name,
                "agent_id": agent.agent_id,
                "context_window": agent.context_window,
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
                pass

        response, _ = self.endpoint_mgr.chat(
            messages=messages,
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            context=agent_id,
        )

        if self.past_actions_svc is not None:
            self.past_actions_svc.record_action(agent_id, "assistant", response)
            self.past_actions_svc.trim_actions(agent_id, agent.max_past_actions or 15)

        return response
