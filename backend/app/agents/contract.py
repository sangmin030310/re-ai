"""Shared format that independent team agents should return.

No legal outcome, carbon savings, price, or vendor qualification should be
presented as verified unless an agent has an auditable source and checks.
"""
from typing import Any, Literal, Protocol
from pydantic import BaseModel, Field


class AgentAction(BaseModel):
    id: str
    label: str
    value: str | None = None


class AgentReply(BaseModel):
    agent: str = "mock_orchestrator"
    status: Literal["needs_information", "review_ready", "error"]
    message: str
    actions: list[AgentAction] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AgentGateway(Protocol):
    def reply(self, *, message: str, profile: dict[str, Any]) -> AgentReply: ...
