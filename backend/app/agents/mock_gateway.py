"""Demonstration-only agent adapter: deterministic, no LLM/network/real validation."""
import re
from .contract import AgentAction, AgentReply


MATERIALS = [
    ("PET", ["pet", "페트"]),
    ("PP", ["pp", "폴리프로필렌"]),
    ("PE", ["pe", "폴리에틸렌"]),
    ("철/금속", ["금속", "철스크랩", "철제", "고철", "알루미늄", "철"]),
    ("혼합 플라스틱", ["혼합플라스틱", "혼합 플라스틱", "혼합재질"]),
    ("플라스틱(미상)", ["플라스틱", "수지"]),
    ("폐지", ["폐지", "종이", "판지"]),
    ("슬러지", ["슬러지", "오니"]),
]


def merge_profile(profile: dict, message: str) -> dict:
    updated = dict(profile)
    lower = message.lower()
    for material, keys in MATERIALS:
        if any(k in lower for k in keys):
            updated["material"] = material
            break

    match = re.search(r"(?:매월|월|한달|한 달|월간)?\s*(\d+(?:\.\d+)?)\s*(톤|ton|t|kg|킬로그램)", lower)
    if match:
        qty = float(match.group(1))
        unit = match.group(2)
        if unit in ("kg", "킬로그램"):
            qty /= 1000
        updated["monthly_ton"] = round(qty, 3)

    if any(token in lower for token in ("오염 없음", "오염없음", "깨끗", "세척 완료", "깨끗한", "비오염")):
        updated["contamination"] = "오염 없음(사용자 진술)"
    elif any(token in lower for token in ("유분", "기름", "오염 있음", "오염있음", "이물질", "오염되어", "오염됨")):
        updated["contamination"] = "오염 가능(사용자 진술)"
    return updated


def analysis_from_profile(profile: dict, selected_route: str | None = None) -> dict:
    missing = []
    if not profile.get("material"):
        missing.append("material")
    if not profile.get("monthly_ton"):
        missing.append("monthly_ton")
    if not profile.get("contamination"):
        missing.append("contamination")

    routes = []
    if not missing:
        material = profile["material"]
        routes = [
            {"id": "direct", "title": "직접 재활용 검토", "tag": "후보", "detail": f"{material} 재질 기준으로 수용업체 조건을 확인해야 합니다.", "checks": ["품질·순도", "업체 수용 규격", "관련 법령 검토"]},
            {"id": "pretreat", "title": "전처리 후 재활용 검토", "tag": "후보", "detail": "분류·세척 등 전처리 필요성과 잔재물 처리를 확인합니다.", "checks": ["오염물 제거 가능성", "전처리 비용", "잔재물 처리"]},
            {"id": "alternative", "title": "대체 처리 경로 검토", "tag": "비교", "detail": "재활용이 어려울 때 적법한 처리 경로를 별도로 확인합니다.", "checks": ["관련 허가", "운반 조건", "증빙 자료"]},
        ]

    return {
        "stage": "경로 검토" if not missing else "정보 확인",
        "missing_fields": missing,
        "profile": profile,
        "routes": routes,
        "selected_route": selected_route,
        "verified": False,
        "disclaimer": "데모 결과입니다. 법규 적합성·업체 수용 여부·비용·탄소 절감은 검증되지 않았습니다.",
        "steps": [
            {"label": "배출 정보 입력", "state": "done" if profile else "current"},
            {"label": "필수 정보 검토", "state": "done" if not missing else "current"},
            {"label": "활용 경로 비교", "state": "current" if not missing else "waiting"},
            {"label": "업체 및 증빙 확인", "state": "waiting"},
            {"label": "사용자 최종 선택", "state": "done" if selected_route else "waiting"},
        ],
    }


class MockAgentGateway:
    def reply(self, *, message: str, profile: dict) -> AgentReply:
        analysis = analysis_from_profile(profile)
        missing = analysis["missing_fields"]
        cleaned = message.strip().lower().replace(" ", "")
        # Demonstration small talk: does not represent a connected language model.
        if cleaned in {"안녕", "안녕!", "안녕?", "안녕하세요", "안녕하세요!", "하이", "hi", "hello", "ㅎㅇ"}:
            return AgentReply(
                status="needs_information" if missing else "review_ready",
                message="안녕하세요! 저는 Re AI 체험용 분석 도우미입니다. 일반적인 자유 대화 AI는 아직 연결되지 않았어요. 폐기물 종류·발생량·오염 상태를 알려주시면 재활용 경로 **예시**를 정리해 드리겠습니다.",
                actions=[AgentAction(id="start_pp", label="PP 폐플라스틱 검토", value="PP 폐플라스틱 월 3톤 발생합니다"), AgentAction(id="start_metal", label="철스크랩 검토", value="철스크랩 월 1톤 발생합니다")],
                warnings=[analysis["disclaimer"]],
            )
        if any(token in cleaned for token in ("너는뭘할수있", "뭘할수있", "무슨기능", "뭐하는서비스", "사용방법", "도움말")):
            return AgentReply(
                status="needs_information" if missing else "review_ready",
                message="현재 체험 모드에서는 ① 폐기물 재질·발생량·오염 여부 입력 ② 가상의 경로 후보 3개 표시 ③ 대화·파일 저장을 지원합니다. 실제 법규·업체 검증 및 자유 대화는 연결되지 않았습니다. 시작하려면 'PP 폐플라스틱 월 3톤'처럼 입력해 주세요.",
                actions=[AgentAction(id="start_pp", label="분석 시작", value="PP 폐플라스틱 월 3톤 발생합니다")],
                warnings=[analysis["disclaimer"]],
            )
        if "material" in missing:
            reply = "폐기물 정보를 정리하고 있습니다. 먼저 **재질이나 폐기물 종류**를 알려주시겠어요? (예: PP, PE, PET, 철스크랩)"
            actions = [AgentAction(id="material_pp", label="PP", value="PP 폐플라스틱입니다"), AgentAction(id="material_pe", label="PE", value="PE 폐플라스틱입니다"), AgentAction(id="material_metal", label="금속", value="철스크랩입니다")]
        elif "monthly_ton" in missing:
            reply = "재질을 확인했습니다. **월간 발생량**은 얼마인가요? 예를 들어 '월 3톤'처럼 알려주세요."
            actions = [AgentAction(id="amount_3", label="월 3톤", value="월 3톤입니다"), AgentAction(id="amount_1", label="월 1톤", value="월 1톤입니다")]
        elif "contamination" in missing:
            reply = "재질과 발생량을 확인했습니다. **유분·이물질 등 오염 여부**를 알려주시면 경로 후보를 정리하겠습니다."
            actions = [AgentAction(id="clean", label="오염 없음", value="오염 없음"), AgentAction(id="dirty", label="오염 있음", value="유분 등 오염 있음")]
        else:
            reply = "입력하신 정보를 바탕으로 **검토 가능한 경로의 예시 3개**를 정리했습니다. 오른쪽 패널에서 후보를 비교하고 선택할 수 있습니다. 실제 업체 조건과 법규 적합성은 별도의 근거 확인이 필요합니다."
            actions = [AgentAction(id="check_docs", label="서류 준비 안내", value="어떤 서류를 준비해야 하나요?")]
            if any(t in message for t in ("서류", "문서", "증빙")):
                reply = "서류 준비는 실제 폐기물 종류·거래 방식·적용 규정에 따라 달라집니다. 우선 **성상 자료, 발생량 기록, 오염 관련 자료, 거래 조건**을 정리하고 담당자의 법적 확인을 거치세요. 문서 보관함에 기존 파일을 업로드할 수 있습니다."
        return AgentReply(status="needs_information" if missing else "review_ready", message=reply, actions=actions, data=analysis, warnings=[analysis["disclaimer"]])
