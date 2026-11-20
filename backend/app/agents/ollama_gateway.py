"""Offline local Ollama chat adapter for Re AI.

Uses only the local Ollama service at http://127.0.0.1:11434.
Messages and project profile are sent to the Ollama process on this PC, not an OpenAI API.
Uploaded document bytes are NOT sent to this adapter.
"""
import json
import logging
import os
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..request_chat import IntakeTurn, intake_instructions
from .contract import AgentAction, AgentReply
from .mock_gateway import analysis_from_profile
from .openai_gateway import SYSTEM

logger = logging.getLogger("uvicorn.error")


class OllamaChatGateway:
    def __init__(self) -> None:
        self.model = os.getenv("OLLAMA_MODEL", "").strip() or "qwen3.5:9b"
        base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Ollama 연결은 이 PC의 로컬 주소(http://127.0.0.1)만 허용합니다.")
        self.endpoint = f"{base_url}/api/chat"

    def generate(self, *, message: str, system: str, history: list[dict] | None = None,
                 schema: dict | None = None) -> str:
        turns = [
            {"role": h["role"], "content": h["content"][-650:]}
            for h in (history or [])[-6:]
            if h.get("role") in {"user", "assistant"} and isinstance(h.get("content"), str)
        ]
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                *turns,
                {"role": "user", "content": message},
            ],
            "stream": False,
            "think": False,
            "keep_alive": "20m",
            "options": {"temperature": 0.35 if schema else 0.55, "num_ctx": 4096, "num_predict": 320 if schema else 240},
        }
        if schema:
            payload["format"] = schema
        req = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=25 if schema else 30) as resp:
            raw = json.load(resp)
        load_ns = raw.get("load_duration")
        total_ns = raw.get("total_duration")
        if isinstance(load_ns, int) and isinstance(total_ns, int):
            logger.info("Ollama %s: total %.2fs (model load %.2fs)", self.model, total_ns / 1e9, load_ns / 1e9)
        answer = (raw.get("message", {}).get("content") or "").strip()
        if not answer:
            raise RuntimeError("Ollama가 빈 답변을 반환했습니다. 모델 설치 상태를 확인하세요.")
        return answer

    def draft_reply(self, *, message: str, profile: dict, history: list[dict]) -> IntakeTurn:
        raw = self.generate(
            message=message, system=intake_instructions(profile), history=history,
            schema=IntakeTurn.model_json_schema(),
        )
        return IntakeTurn.model_validate_json(raw)

    def reply(self, *, message: str, profile: dict, history: list[dict] | None = None) -> AgentReply:
        analysis = analysis_from_profile(profile)
        system = SYSTEM + "\n현재 사용자가 제공한 정보(검증 전): " + json.dumps(profile, ensure_ascii=False)
        answer = self.generate(message=message, system=system, history=history)
        missing = analysis["missing_fields"]
        actions = []
        if "material" in missing:
            actions = [AgentAction(id="pp", label="PP", value="PP 폐플라스틱입니다"), AgentAction(id="metal", label="철스크랩", value="철스크랩입니다")]
        elif "monthly_ton" in missing:
            actions = [AgentAction(id="ton_3", label="월 3톤", value="월 3톤입니다")]
        elif "contamination" in missing:
            actions = [AgentAction(id="clean", label="오염 없음", value="오염 없음"), AgentAction(id="dirty", label="오염 있음", value="오염 있음")]
        return AgentReply(
            agent="ollama_chat",
            status="needs_information" if missing else "review_ready",
            message=answer,
            actions=actions,
            data=analysis,
            warnings=[analysis["disclaimer"]],
        )
