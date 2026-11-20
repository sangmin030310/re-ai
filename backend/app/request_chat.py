"""Collect and review request information in the project conversation."""
import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .agents.contract import AgentAction, AgentReply
from .agents.mock_gateway import MATERIALS, analysis_from_profile

FIELDS = (
    ("material", "재질", "PP"),
    ("monthly_ton", "월간 발생량", "월 3톤"),
    ("region", "배출 지역", "배출 지역: 전주"),
    ("contamination", "오염 상태", "오염 없어요"),
    ("packaging", "포장 상태", "톤백에 담아요"),
)
TEXT_LABELS = (
    ("region", "배출 지역", 50),
    ("packaging", "포장 상태", 100),
    ("contamination", "오염 상태", 100),
    ("notes", "추가 전달 사항", 500),
)
CITIES = r"서울|전주|익산|완주|군산|김제|부안|수원|인천|대전|광주|부산|대구|울산|세종|청주|천안"
CITY_NAME = rf"(?P<city>{CITIES})(?:특별자치시|특별시|광역시|시|군)?"
REGION_ANSWER = re.compile(
    rf"(?:(?:배출\s*지역|지역|공장|사업장)(?:은|는|이|가)?\s*(?:[:：]\s*)?)?"
    rf"{CITY_NAME}\s*"
    r"(?:야|이야|지|죠|요|입니다|이에요|예요|에요|이구요|이고요|"
    r"에\s*(?:있어요|있습니다|있어)|"
    r"(?:으?로)\s*(?:수정(?:해)?|변경(?:해)?|바꿔|정정(?:해)?|적어|써)(?:\s*(?:줘|주세요))?)?"
)
PACKAGING = r"톤백|마대|벌크|팔레트|드럼통|박스"
QUANTITY = re.compile(r"(?<![\d.,-])(\d[\d,]*(?:\.\d+)?)\s*(킬로그램|kg|톤|ton\b|t\b)", re.I)
CONTAMINATION_CLEAR = re.compile(r"(?:오염|유분|기름|이물질)(?:이|은|는|도)?\s*(?:없|X\b)", re.I)
CONTAMINATION_DECLARED = re.compile(r"(?:오염|유분|기름|이물질)(?:이|은|는|도)?\s*(?:있|묻|섞)", re.I)
ASK_FOR_HELP = re.compile(
    r"모르|몰라|모름|뭔지|뭐(?:예요|야|지|죠|에요)|무슨\s*뜻"
    r"|어떻게\s*(?:확인|알아|적|써|쓰|입력|구하)|확인\s*(?:방법|할\s*수\s*없)"
    r"|맞나|맞는지|맞아요\s*\?"
)
DEFER_FIELD = re.compile(r"미확인|확인\s*필요(?:로)?|나중에\s*확인|건너\s*뛰|넘어\s*가|보류")
FIELD_WORDS = {
    "material": r"재질|소재|종류",
    "monthly_ton": r"발생량|물량|중량|수량|무게",
    "region": r"배출\s*지역|주소|지역|소재지",
    "contamination": r"오염|이물질|유분|기름",
    "packaging": r"포장|보관\s*상태|톤백|마대|포대",
}
FIELD_HELP = {
    "material": "제품이나 포장재에 적힌 재질 표시를 보거나, 원자재 명세서에서 사용한 소재 이름을 확인해 보세요. 예를 들어 PP 표시를 확인했다면 **PP**라고 답하면 됩니다.",
    "monthly_ton": "최근 한 달 계근표나 반출 내역에서 같은 폐기물의 무게를 합해 보세요. kg로 알고 있다면 **월 800kg**처럼 그대로 답해도 됩니다.",
    "region": "폐기물이 실제로 발생하는 공장이나 사업장의 주소에서 **시·군 이름**을 확인해 주세요. 예를 들어 전주시 사업장이라면 **배출 지역: 전주**라고 답하면 됩니다.",
    "contamination": "폐기물에 기름, 물기, 먼지 또는 다른 재질이 섞여 있는지 보는 항목이에요. 확인했다면 **오염 없어요** 또는 **기름이 묻어 있어요**처럼 알려주세요.",
    "packaging": "폐기물이 지금 어디에 담겨 있거나 어떻게 쌓여 있는지 보는 항목이에요. **큰 톤백에 담겨 있어요**, **상자에 담겨 있어요**, **아직 포장 안 했어요**처럼 답하면 됩니다.",
}
DEFERRED = "확인 필요"
DEFERRABLE_FIELDS = {"contamination", "packaging"}


def merge_shipping_details(profile: dict, message: str) -> None:
    region = REGION_ANSWER.fullmatch(message.strip().rstrip(".!?")) or re.search(
        rf"{CITY_NAME}(?:에서|에\s*있는|\s*공장|\s*사업장)", message
    )
    if region:
        profile["region"] = region["city"]
    packaging = re.search(rf"({PACKAGING})(?:으?로|에)?\s*(?:포장|보관|적재|담)", message)
    if packaging:
        profile["packaging"] = f"{packaging[1]} 포장"
    for field, label, limit in TEXT_LABELS:
        explicit = labeled_value(message, label)
        if explicit:
            profile[field] = explicit[:limit]


def labeled_value(message: str, label: str) -> str:
    stop = r"[^\n]+" if label == "추가 전달 사항" else r"[^\n,;.!?]+"
    match = re.search(rf"{label}\s*[:：]\s*({stop})", message)
    return match[1].strip().rstrip(".") if match else ""


def missing_fields(profile: dict) -> list[tuple[str, str, str]]:
    return [(key, label, example) for key, label, example in FIELDS
            if not profile.get(key) or (key == "material" and profile[key] == "플라스틱(미상)")]


class DraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    material: Literal["PP", "PE", "PET", "철/금속", "혼합 플라스틱", "폐지", "슬러지", "기타"] | None = None
    monthly_ton: float | None = Field(default=None, ge=0.001, le=100000, allow_inf_nan=False)
    region: Annotated[str, StringConstraints(min_length=1, max_length=50)] | None = None
    contamination: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    packaging: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    notes: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = None


class IntakeTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reply: str = Field(min_length=1, max_length=1800)
    updates: DraftUpdate


INTAKE_SYSTEM = """너는 폐기물 요청서를 사용자와 함께 작성하는 한국어 대화 도우미 Re AI다.
최근 대화와 현재 초안을 보고 사용자의 마지막 말에 먼저 답한다. 자연스러운 존댓말로 2~4문장을 쓴다.
이미 말한 정보는 기억하고 되묻지 않는다. 사용자가 한꺼번에 알려주면 해당 정보를 모두 받아 적는다.
모른다고 하거나 중간에 다른 질문을 하면 확인 방법이나 질문의 답을 먼저 설명한다. 서류 질문을 무조건 반복하지 않는다.
대화를 이어가는 데 필요할 때만 질문을 한 가지 한다. 재질·월간 발생량·배출 지역이 모두 있으면 '추천 업체 보기'로 이어갈 수 있다.
오염이나 포장 상태를 더 물을 때는 선택 항목이며 나중에 확인할 수 있음을 알려준다.
reply는 사용자에게 보일 답변이다. updates에는 현재 발화가 확인하거나 수정한 항목만 넣는다.
질문에 나오는 단어, 예시, 가정, 추측은 초안에 기록하지 않는다. 앞선 대화는 표현이나 짧은 대답의 뜻을 해석하는 데 쓴다.
monthly_ton은 월 단위 톤이다. 월간 물량이 분명할 때만 kg을 톤으로 바꿔 기록한다. 지역은 시·군의 통상 명칭으로 쓴다(예: 전주시→전주).
오염이나 포장 상태를 나중에 확인하겠다고 사용자가 명시하면 해당 항목에 '확인 필요'라고 쓴다.
배출 지역, 재질, 월간 발생량을 모르면 확인 방법을 안내하고 해당 값은 건드리지 않는다.
법규, 업체 허가, 가격은 검증된 것처럼 말하지 않는다. 사용자를 대신해 요청서를 저장하거나 연락했다고 말하지 않는다.
"""


def intake_instructions(profile: dict) -> str:
    current = {key: profile.get(key) for key in DraftUpdate.model_fields}
    missing = [label for _, label, _ in missing_fields(profile)]
    return (
        f"{INTAKE_SYSTEM}\n현재 초안: {json.dumps(current, ensure_ascii=False)}"
        f"\n비어 있는 항목: {', '.join(missing) or '없음'}"
    )


def interpret_request_message(profile: dict, message: str) -> tuple[dict, str | None, list[AgentAction]]:
    clauses = re.split(r"[.!?](?=\s|$)|[,;](?=\s)|\n|(?:인데|예요|입니다)(?=\s)", message)
    help_clause = next((clause for clause in clauses if ASK_FOR_HELP.search(clause) or DEFER_FIELD.search(clause)), None)
    if help_clause is None:
        return merge_request_profile(profile, message), None, []

    for clause in clauses:
        if not ASK_FOR_HELP.search(clause) and not DEFER_FIELD.search(clause):
            profile = merge_request_profile(profile, clause)
    missing = missing_fields(profile)
    field = next((key for key, pattern in FIELD_WORDS.items() if re.search(pattern, help_clause)), None)
    if field is None and missing:
        field = missing[0][0]
    if field is None:
        return profile, "어느 항목이 헷갈리시나요? **오염 상태가 뭐예요?**처럼 항목을 말해 주시면 확인 방법을 알려드릴게요.", []

    label = next(label for key, label, _ in FIELDS if key == field)
    if DEFER_FIELD.search(help_clause) and field in DEFERRABLE_FIELDS:
        updated = {**profile, field: DEFERRED}
        return updated, f"**{label}** 항목을 **확인 필요**로 표시했어요. 나중에 확인한 내용을 채팅이나 직접 수정에서 바꿀 수 있습니다.", []

    guidance = f"괜찮아요. **{label}**은 이렇게 확인해 보세요.\n\n{FIELD_HELP[field]}"
    if field in DEFERRABLE_FIELDS:
        guidance += " 지금 바로 확인하기 어렵다면 아래에서 나중에 확인할 수 있어요."
        action = AgentAction(id=f"defer-{field}", label="나중에 확인하기", value=f"{label} 나중에 확인할게요")
        return profile, guidance, [action]
    guidance += " 업체를 찾으려면 이 항목이 필요해요. 확인할 수 있을 때 같은 요청서에서 이어서 작성하면 됩니다."
    return profile, guidance, []


def merge_request_profile(profile: dict, message: str) -> dict:
    updated = dict(profile)
    remaining = missing_fields(profile)
    expected = remaining[0][0] if remaining else None
    clean = message.strip().rstrip(".!?")
    # Use only a recognized statement or an answer to the requested field.
    material = next((
        name for name, terms in MATERIALS
        if any(re.search(rf"(?<![a-z]){term}(?![a-z])", message, re.I) if term.isascii()
               else term in message for term in terms)
    ), None)
    if material == "플라스틱(미상)" and updated.get("material"):
        material = None
    if material:
        updated["material"] = material

    quantities = list(QUANTITY.finditer(message))
    if len(quantities) == 1:
        amount, unit = quantities[0].groups()
        value = float(amount.replace(",", ""))
        if unit.lower() in {"kg", "킬로그램"}:
            value /= 1000
        if 0.001 <= value <= 100_000:
            updated["monthly_ton"] = round(value, 3)

    if CONTAMINATION_CLEAR.search(message) or re.fullmatch(r"깨끗(?:해|해요|합니다)", clean) or (
        expected == "contamination" and re.fullmatch(r"없(?:음|어|어요|습니다)?", clean)
    ):
        updated["contamination"] = "오염 없음(사용자 진술)"
    elif CONTAMINATION_DECLARED.search(message) or (expected == "contamination" and re.fullmatch(r"있(?:음|어|어요|습니다)?", clean)):
        updated["contamination"] = "오염 있음(사용자 진술)"

    merge_shipping_details(updated, message)
    if re.fullmatch(rf"(?:{PACKAGING})(?:입니다|이에요|예요)?", clean):
        updated["packaging"] = f"{re.match(PACKAGING, clean)[0]} 포장"
    if re.search(r"(?:아직\s*)?(?:미포장|포장(?:을|은)?\s*안\s*(?:했|한|되어|돼)|포장(?:은|이)?\s*없)", clean):
        updated["packaging"] = "미포장(사용자 진술)"
    elif re.search(r"상자(?:에|로)\s*(?:담|포장|보관)", clean):
        updated["packaging"] = "상자 포장"
    return updated


def request_reply(profile: dict, guidance: str | None, actions: list[AgentAction], *, continue_intake: bool) -> AgentReply:
    missing = missing_fields(profile)
    required = [(key, label, example) for key, label, example in missing if key not in DEFERRABLE_FIELDS]
    if required:
        _, label, example = required[0]
        text = f"**{label}**을 알려주세요. 예를 들어 **{example}**처럼 답하면 요청서에 반영됩니다."
    else:
        text = "입력한 내용을 바탕으로 **추천 업체 보기**에서 후보를 비교할 수 있어요."
        if missing:
            _, label, example = missing[0]
            text = f"{text} **{label}**을 알고 있다면 **{example}**처럼 추가로 알려주세요."
    if guidance:
        text = f"{guidance}\n\n{text}" if continue_intake else guidance
    return AgentReply(
        agent="request_draft", status="needs_information" if required else "review_ready",
        message=text, actions=actions, data=analysis_from_profile(profile),
    )
