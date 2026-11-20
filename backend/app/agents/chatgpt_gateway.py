"""Consume streamed Responses requests authorized by an individual ChatGPT plan."""
import json

from ..chatgpt_connection import (
    RESOURCE, ChatGPTError, RemoteError, available_models, exchange, load_state, lock, usable_account,
)
from ..request_chat import IntakeTurn, intake_instructions
from .contract import AgentReply
from .mock_gateway import analysis_from_profile
from .openai_gateway import chat_instructions


def consume_response(stream) -> str:
    text = []
    event_data = []
    for line in stream:
        line = line.decode("utf-8").rstrip("\r\n")
        if line.startswith("data:"):
            event_data.append(line[5:].lstrip())
        elif not line and event_data:
            event = json.loads("\n".join(event_data))
            event_data.clear()
            kind = event.get("type")
            if kind == "response.output_text.delta":
                text.append(event.get("delta", ""))
            elif kind == "response.completed":
                answer = "".join(text).strip()
                if answer:
                    return answer
                break
            elif kind in {"response.failed", "error", "response.incomplete"}:
                error = (event.get("response") or {}).get("error") or event.get("error") or event
                code = error.get("code", "")
                status = 429 if code == "subscription_sharing_usage_limit_exceeded" else 403 if code in {
                    "subscription_sharing_user_not_eligible", "chatpass_v2_scope_not_authorized",
                } else 502
                raise RemoteError(status, code)
    raise ChatGPTError("ChatGPT 응답이 중간에 끝났습니다. 다시 시도해 주세요.")


class ChatGPTPlanGateway:
    def generate(self, *, message: str, instructions: str, history: list[dict], structured: bool = False) -> str:
        with lock:
            account = usable_account(load_state())
            token = account["access_token"]
            model = account.get("model")
            if not model:
                catalog = available_models(account)
                if not catalog:
                    raise ChatGPTError("이 계정에서 사용할 수 있는 ChatGPT 모델이 없습니다.")
                model = next((option["slug"] for option in catalog if option["slug"] == "gpt-6-luna"), catalog[0]["slug"])

        turns = [
            {"type": "message", "role": turn["role"], "content": turn["content"][-900:]}
            for turn in history[-8:] if turn["role"] in {"user", "assistant"}
        ]
        turns.append({"type": "message", "role": "user", "content": message})
        payload = {
            "model": model, "instructions": instructions, "input": turns, "store": False, "stream": True,
        }
        if structured:
            payload["text"] = {"format": {"type": "json_schema", "name": "request_draft",
                                           "schema": IntakeTurn.model_json_schema(), "strict": False}}
        with exchange(f"{RESOURCE}/responses", token=token, payload=payload) as stream:
            return consume_response(stream)

    def draft_reply(self, *, message: str, profile: dict, history: list[dict]) -> IntakeTurn:
        instructions = intake_instructions(profile) + "\nreply와 updates를 포함한 JSON 객체를 반환한다."
        raw = self.generate(message=message, instructions=instructions, history=history, structured=True)
        return IntakeTurn.model_validate_json(raw)

    def reply(self, *, message: str, profile: dict, history: list[dict], role: str = "supplier") -> AgentReply:
        instructions = chat_instructions(profile, role)
        text = self.generate(message=message, instructions=instructions, history=history)
        data = analysis_from_profile(profile)
        return AgentReply(agent="chatgpt_chat", status="needs_information" if role == "supplier" and data["missing_fields"] else "review_ready", message=text, data=data)
