"""Connection points for team agents in the matching and deal flow.

The UI never calls an agent directly. The server calls one object that follows
``MatchingAgent`` and passes the results to the screens in fixed slots:

* ``assess_request``   -> 요청서 화면의 '에이전트 검토' 카드 (법적 지위, 근거, 미확인 항목)
* ``assess_companies`` -> 업체 카드의 점수·근거·경고
* ``deal_documents``   -> 거래 건의 서류 체크리스트

To plug in a real agent, set ``REAI_MATCHING_AGENT=package.module:ClassName``.
The class is created once with no arguments. If it raises, the server falls back to
the rule-based default and shows a warning instead of failing the screen.
"""
from __future__ import annotations

import importlib
import logging
import os
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class Evidence(BaseModel):
    title: str
    detail: str = ""
    source: str = ""          # 법령명, 고시, 업체 회신 등 출처
    checked_at: str | None = None


class RequestAssessment(BaseModel):
    source: str = "rule_based"
    legal_status: str | None = None          # None이면 화면에 '확인되지 않음'
    summary: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    unverified: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


class CompanyAssessment(BaseModel):
    source: str = "rule_based"
    score: float | None = None               # 0~100. None이면 점수를 표시하지 않음
    summary: str = ""
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class DocumentRequirement(BaseModel):
    key: str
    label: str
    owner: Literal["supplier", "recycler", "carrier", "any"] = "any"
    stage: Literal["before_agreement", "before_transport", "after_delivery"] = "after_delivery"
    note: str = ""
    source: str = "rule_based"


class MatchingAgent(Protocol):
    def assess_request(self, request: dict[str, Any], context: dict[str, Any]) -> RequestAssessment: ...

    def assess_companies(
        self, request: dict[str, Any], companies: list[dict[str, Any]], context: dict[str, Any],
    ) -> dict[str, CompanyAssessment]: ...

    def deal_documents(
        self, request: dict[str, Any], terms: dict[str, Any], context: dict[str, Any],
    ) -> list[DocumentRequirement]: ...


class RuleBasedMatchingAgent:
    """Demo default. It states what is unknown instead of guessing legal results."""

    def assess_request(self, request, context):
        warnings = []
        unverified = ["법적 지위(폐기물·순환자원·부산물) 판단", "관할 기관 신고 내용과 실제 배출 성상의 일치 여부"]
        missing = []
        if request.get("contamination") in (None, "", "확인 필요"):
            missing.append("오염 상태")
        if request.get("packaging") in (None, "", "확인 필요"):
            missing.append("포장 상태")
        if not request.get("attachment_ids"):
            warnings.append("사진이나 성상분석표가 없으면 가공업체가 반입 여부를 판단하기 어렵습니다.")
        stated = request.get("legal_status")
        if stated and stated != "확인 전":
            summary = f"배출업체가 '{stated}'(으)로 입력했습니다. 법령 검토 에이전트가 연결되면 근거와 함께 확인합니다."
        else:
            summary = "법적 지위는 아직 확인되지 않았습니다. 법령 검토 에이전트 연결 전까지 업체 회신으로 확인하세요."
        return RequestAssessment(
            legal_status=None, summary=summary, warnings=warnings, unverified=unverified, missing_fields=missing,
        )

    def assess_companies(self, request, companies, context):
        results = {}
        for company in companies:
            match = company.get("match") or {"matched": [], "unmet": []}
            score = None if match["unmet"] else 60.0
            warnings = []
            if score is not None:
                trust = company.get("trust") or {}
                if trust.get("permit_verified"):
                    score += 20
                elif trust.get("permit_expired"):
                    warnings.append("등록된 허가의 유효기간이 지났습니다.")
                elif trust.get("permit_registered"):
                    warnings.append("허가 정보가 등록됐지만 운영자 확인 전입니다.")
                else:
                    warnings.append("허가 정보가 등록되지 않았습니다. 문의할 때 허가증을 요청하세요.")
                distance = company.get("distance_km")
                if distance is not None:
                    score += max(0.0, 20 - distance / 10)
                score = round(min(score, 100.0), 1)
            results[company["id"]] = CompanyAssessment(
                score=score, reasons=list(match["matched"]), warnings=warnings,
                summary="재질·지역·수용량 규칙과 허가 확인 여부로 계산한 시연용 점수입니다.",
            )
        return results

    def deal_documents(self, request, terms, context):
        documents = [
            DocumentRequirement(key="sample", label="성상분석표 또는 샘플 사진", owner="supplier", stage="before_agreement",
                                note="가공업체가 반입 기준을 확인할 때 사용합니다."),
            DocumentRequirement(key="contract", label="위탁·매매 계약서", owner="any", stage="before_transport",
                                note="거래 조건(단가, 주기, 책임 범위)을 서면으로 남깁니다."),
            DocumentRequirement(key="handover", label="인계서(전자인계 등록 확인)", owner="supplier", stage="before_transport",
                                note="적용 대상 여부와 방식은 법령 검토 에이전트 결과로 확정합니다."),
            DocumentRequirement(key="weighing", label="계량증명서", owner="recycler", stage="after_delivery"),
            DocumentRequirement(key="processing", label="처리·재활용 확인서", owner="recycler", stage="after_delivery"),
        ]
        if terms.get("transport_by") in ("supplier", "recycler"):
            documents.insert(3, DocumentRequirement(
                key="transport_permit", label="운송업체 수집·운반 허가 확인", owner=terms["transport_by"], stage="before_transport",
            ))
        return documents


_agent: MatchingAgent | None = None
_agent_error: str | None = None


def matching_agent() -> MatchingAgent:
    global _agent, _agent_error
    if _agent is not None:
        return _agent
    target = os.getenv("REAI_MATCHING_AGENT", "").strip()
    if target:
        try:
            module_name, _, class_name = target.partition(":")
            _agent = getattr(importlib.import_module(module_name), class_name)()
            return _agent
        except Exception as error:  # pragma: no cover - depends on team code
            logger.exception("REAI_MATCHING_AGENT could not be loaded")
            _agent_error = f"매칭 에이전트를 불러오지 못했습니다: {error}"
    _agent = RuleBasedMatchingAgent()
    return _agent


def reset_agent() -> None:
    global _agent, _agent_error
    _agent, _agent_error = None, None


FALLBACK = RuleBasedMatchingAgent()


def _fallback_warning(error: Exception) -> str:
    logger.exception("matching agent call failed", exc_info=error)
    return "연결된 에이전트가 응답하지 않아 기본 규칙으로 표시합니다."


def assess_request(request: dict, context: dict) -> dict:
    try:
        result = matching_agent().assess_request(request, context)
    except Exception as error:
        result = FALLBACK.assess_request(request, context)
        result.warnings.insert(0, _fallback_warning(error))
    if _agent_error:
        result.warnings.insert(0, _agent_error)
    return result.model_dump()


def assess_companies(request: dict, companies: list[dict], context: dict) -> dict[str, dict]:
    try:
        results = matching_agent().assess_companies(request, companies, context)
    except Exception as error:
        results = FALLBACK.assess_companies(request, companies, context)
        for item in results.values():
            item.warnings.insert(0, _fallback_warning(error))
    return {key: value.model_dump() for key, value in results.items()}


def deal_documents(request: dict, terms: dict, context: dict) -> list[dict]:
    try:
        documents = matching_agent().deal_documents(request, terms, context)
    except Exception as error:
        _fallback_warning(error)
        documents = FALLBACK.deal_documents(request, terms, context)
    return [document.model_dump() for document in documents]
