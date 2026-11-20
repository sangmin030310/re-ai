"""Read-only workspace actions available from the common chat."""
import re

from .agents.contract import AgentAction, AgentReply
from .deals import list_deals
from .matching import SupplySearch, search_supplies
from .request_chat import merge_request_profile


SUPPLY = AgentAction(id="open-supply-market", label="공급처 찾기")
DEMANDS = AgentAction(id="open-demands", label="우리 수요 공고")
DEALS = AgentAction(id="open-deals", label="거래 건 열기")


def workspace_help(role, account_mode):
    if role == "recycler":
        if account_mode:
            return AgentReply(agent="workspace_chat", status="review_ready",
                              message="안녕하세요! 필요한 재질과 물량을 알려주시면 공개 공급처를 찾을게요. 거래 진행 상태나 수요 공고 작성 방법도 물어보세요.",
                              actions=[SUPPLY, DEMANDS])
        return AgentReply(agent="workspace_chat", status="review_ready",
                          message="안녕하세요! 반입 조건과 거래 진행 절차를 안내할 수 있어요. 받은 문의는 기업 문의함에서 확인하세요.")
    return AgentReply(agent="workspace_chat", status="review_ready",
                      message="안녕하세요! 받은 운송 견적 요청이나 진행 중인 운송 건을 물어보세요. 상차 전에 확인할 항목도 안내할 수 있어요.",
                      actions=[DEALS])


def supply_reply(workspace, prompt, criteria):
    result = search_supplies(SupplySearch(**criteria, message=prompt[:1000]), workspace)
    found = result["results"]
    requirements = result["criteria"]
    scope = " · ".join(str(requirements[key]) for key in ("region", "material") if key in requirements)
    amount = requirements.get("monthly_ton")
    scope = " · ".join(filter(None, (scope, f"필요 물량 {amount:g}톤" if amount else "")))
    prefix = f"검색 조건은 **{scope}**입니다. " if scope else ""
    if not found:
        message = prefix + "조건에 맞는 공개 물량이 없어요. 다른 지역이나 재질로 찾아볼 수 있습니다."
    else:
        message = prefix + f"공개 물량 **{len(found)}건**을 찾았어요."
        if amount and all(row["monthly_ton"] < amount for row in found):
            message += " 한 업체에서 필요한 물량을 전부 채우기는 어려워요."
        message += "\n\n" + "\n".join(
            f"• {row['name']} · {row['region']} · {row['material']} {row['monthly_ton']:g}톤" for row in found[:3]
        )
        message += "\n\n공급처 찾기에서 상세 조건을 보고 문의할 수 있어요."
    return AgentReply(agent="workspace_supply", status="review_ready", message=message, actions=[SUPPLY]), requirements


def deal_reply(workspace, *, carrier, quote_only):
    active = [item for item in list_deals(workspace) if item["status"] not in {"completed", "cancelled"}]
    requested = [item for item in active if item["my_role"] == "carrier_candidate"]
    if quote_only:
        active = requested
        heading = f"받은 운송 견적 요청은 **{len(active)}건**이에요."
    elif carrier:
        active = [item for item in active if item["my_role"] == "carrier"]
        heading = f"맡아서 진행 중인 운송 건은 **{len(active)}건**이에요."
    else:
        heading = f"진행 중인 거래 건은 **{len(active)}건**이에요."
    if active:
        active.sort(key=lambda item: not item["next_action"]["mine"])
        heading += "\n\n" + "\n".join(
            f"• {item['route']} · {item['material']} {item['quantity_ton']:g}톤 · {item['next_action']['label']}"
            for item in active[:3]
        )
    return AgentReply(agent="workspace_deals", status="review_ready", message=heading, actions=[DEALS])


def role_chat(workspace, role, prompt, profile, greeting):
    account_mode = workspace.startswith("company-")
    if greeting:
        return workspace_help(role, account_mode), profile
    compact = re.sub(r"\s+", "", prompt)
    if role == "recycler" and account_mode:
        if "수요공고" in compact:
            return AgentReply(agent="workspace_chat", status="review_ready", actions=[DEMANDS],
                              message="우리 수요 공고에서 필요한 재질, 월 필요량, 반입 가능 지역과 반입 조건을 입력해 공고를 올릴 수 있어요."), profile
        criteria = profile.get("supply_criteria", {})
        parsed = merge_request_profile({}, prompt)
        if any(word in compact for word in ("공급처", "공개물량", "공개된", "구할수", "구하고", "찾고")) or any(
            key in parsed for key in ("material", "monthly_ton", "region")
        ) or (criteria and any(word in compact for word in ("근처", "인근", "전국", "지역상관없"))):
            reply, next_criteria = supply_reply(workspace, prompt, criteria)
            return reply, {**profile, "supply_criteria": next_criteria}
    if role == "carrier" and ("상차전" in compact or "상차준비" in compact):
        return AgentReply(agent="workspace_chat", status="review_ready", actions=[DEALS],
                          message="상차 전에는 **상차·하차 주소와 시간**, **차량에 맞는 포장·예정 물량**, **상·하차 장비와 현장 담당자 연락처**를 확인하세요. 맡은 운송 건의 상세 화면에서 확인하고 협의할 수 있어요."), profile
    quote_only = role == "carrier" and "견적" in compact and any(word in compact for word in ("요청", "받은", "몇건"))
    if quote_only or any(word in compact for word in ("거래건", "운송건", "운송현황", "거래현황")):
        return deal_reply(workspace, carrier=role == "carrier", quote_only=quote_only), profile
    return None, profile
