"""Optional OpenAI Responses API gateway. Never used without an explicit backend API key.

This is a chat adapter, not a legal/recycling validation agent. Uploaded files are
NOT sent to the provider. Only text conversation and waste fields are included.
"""
import json
import os

from ..request_chat import IntakeTurn, intake_instructions
from .contract import AgentReply, AgentAction
from .mock_gateway import analysis_from_profile

SYSTEM = """너는 산업폐기물 자원순환 서비스를 돕는 한국어 대화형 조력자 Re AI다.
자연스러운 인사와 자유로운 질문에 맥락 있게 답하라. 대화는 친절하고 간결하게.
현재 운영 시스템은 데모이다. 실제 법규 준수, 폐기물 분류, 처리 허가,
업체 자격, 비용 및 탄소 절감량은 검증하지 못한다. 검증되지 않은 결과를
확정적으로 말하지 말고, 근거가 없으면 근거 부족이라고 밝혀라.
정보를 수집할 때 재질, 월간 발생량, 오염 여부 중 빠진 항목을 자연스럽게
질문할 수 있지만, 인사나 별개 질문을 무시하고 같은 질문만 반복하지 마라.
사용자가 최종 선택해야 하며, 실제 허가·계약·법규 준수의 최종 판단은 전문가에게 확인하라.
내부 필드에 없는 데이터를 알고 있는 척하지 마라.
"""

ROLE_CONTEXT = {
    "recycler": "사용자는 가공업체다. 필요한 재질·물량, 공개 공급처 탐색, 반입 조건, 수요 공고와 거래 절차를 안내하라.",
    "carrier": "사용자는 운송업체다. 견적, 상차·하차, 차량·포장·현장 조건과 배차 절차를 안내하라.",
}


def chat_instructions(profile: dict, role: str) -> str:
    if role == "supplier":
        return SYSTEM + "\n현재 입력된 폐기물 정보(사용자 진술): " + json.dumps(profile, ensure_ascii=False)
    return SYSTEM + "\n" + ROLE_CONTEXT[role] + (
        " 해당 역할에 배출업체용 요청서 항목을 수집하지 마라."
        " 조회되지 않은 업체·견적·거래 상태를 지어내지 말고, 협의 또는 사용자가 직접 확인할 화면을 안내하라."
    )


class OpenAIChatGateway:
    def __init__(self) -> None:
        from openai import OpenAI
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"].strip(), timeout=25.0, max_retries=0)
        self.model = os.getenv("OPENAI_MODEL", "").strip() or "gpt-6-luna"

    def request_args(self, *, message: str, instructions: str, history: list[dict] | None) -> dict:
        turns = [
            {"role": h["role"], "content": h["content"][-900:]}
            for h in (history or [])[-8:]
            if h.get("role") in {"user", "assistant"} and isinstance(h.get("content"), str)
        ]
        turns.append({"role": "user", "content": message})
        kwargs = {
            "model": self.model, "instructions": instructions, "input": turns,
            "max_output_tokens": 450, "store": False,
        }
        if self.model == "gpt-6-luna":
            kwargs["reasoning"] = {"effort": "none"}
        return kwargs

    def draft_reply(self, *, message: str, profile: dict, history: list[dict]) -> IntakeTurn:
        response = self.client.responses.parse(
            **self.request_args(message=message, instructions=intake_instructions(profile), history=history),
            text_format=IntakeTurn,
        )
        if response.status != "completed" or response.output_parsed is None:
            raise RuntimeError("OpenAI 요청서 응답을 확인할 수 없습니다.")
        return response.output_parsed

    def reply(self, *, message: str, profile: dict, history: list[dict] | None = None, role: str = "supplier") -> AgentReply:
        analysis = analysis_from_profile(profile)
        instructions = chat_instructions(profile, role)
        response = self.client.responses.create(
            **self.request_args(message=message, instructions=instructions, history=history),
        )
        answer = (response.output_text or "").strip()
        if not answer:
            raise RuntimeError("AI 응답이 비어 있습니다.")
        missing = analysis["missing_fields"] if role == "supplier" else []
        actions = []
        if "material" in missing:
            actions = [AgentAction(id="pp", label="PP", value="PP 폐플라스틱입니다"), AgentAction(id="metal", label="철스크랩", value="철스크랩입니다")]
        elif "monthly_ton" in missing:
            actions = [AgentAction(id="ton_3", label="월 3톤", value="월 3톤입니다")]
        elif "contamination" in missing:
            actions = [AgentAction(id="clean", label="오염 없음", value="오염 없음"), AgentAction(id="dirty", label="오염 있음", value="오염 있음")]
        return AgentReply(
            agent="openai_chat",
            status="needs_information" if missing else "review_ready",
            message=answer,
            actions=actions,
            data=analysis,
            warnings=[analysis["disclaimer"]],
        )
