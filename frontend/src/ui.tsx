import { useState } from 'react'
import { BadgeCheck, CircleAlert, ShieldQuestion, Sparkles } from 'lucide-react'
import type { AgentAssessment, Evidence, RequestAssessment, Trust } from './lib/api'

export const won = (value: number | null | undefined) => value == null ? '—' : `${value.toLocaleString('ko-KR')}원`
export const tons = (value: number | null | undefined) => value == null ? '—' : `${Number(value.toFixed(3))}톤`
export const km = (value: number | null | undefined) => value == null ? null : value < 3 ? '같은 시·군' : `약 ${Math.round(value)}km`
export const errorText = (error: unknown) => error instanceof Error ? error.message : '요청을 처리하지 못했습니다.'
export const dateTime = (value: string | null | undefined) => {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('ko-KR', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}
export const priceSummary = (priceType: string | null | undefined, unitPrice: number | null | undefined) => {
  if (!priceType) return '가격 미정'
  if (priceType === '무상') return '대금 없음'
  if (priceType === '협의') return '가격 협의'
  return `${priceType} · 톤당 ${won(unitPrice)}`
}

/** Permit badge. 'verified' only when an operator checked the current permit details. */
export function TrustBadge({ trust, compact = false }: { trust?: Trust | null; compact?: boolean }) {
  if (!trust) return null
  if (trust.permit_verified) {
    return <span className="trust-badge verified" title={`${trust.permit_type} · ${trust.permit_number}${trust.verify_note ? ` · ${trust.verify_note}` : ''}`}>
      <BadgeCheck size={14} /> 허가 확인{!compact && trust.permit_type ? ` · ${trust.permit_type}` : ''}
    </span>
  }
  if (trust.permit_expired) return <span className="trust-badge warning"><CircleAlert size={14} /> 허가 유효기간 지남</span>
  if (trust.permit_registered) {
    return <span className="trust-badge pending" title={`${trust.permit_type} · ${trust.permit_number}`}>
      <ShieldQuestion size={14} /> 허가 등록 · 확인 전
    </span>
  }
  return <span className="trust-badge none"><ShieldQuestion size={14} /> 허가 정보 없음</span>
}

export function TrustStats({ trust }: { trust?: Trust | null }) {
  if (!trust) return null
  const { completed_deals, reply_rate, inquiries_received } = trust.stats
  return <span className="trust-stats">
    완료 거래 {completed_deals}건
    {inquiries_received > 0 && <> · 답장률 {reply_rate}%</>}
  </span>
}

function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (!evidence.length) return null
  return <ul className="agent-evidence">{evidence.map((item, index) => <li key={index}>
    <strong>{item.title}</strong>{item.detail && <> — {item.detail}</>}
    {(item.source || item.checked_at) && <small> {item.source}{item.checked_at ? ` · ${item.checked_at} 기준` : ''}</small>}
  </li>)}</ul>
}

/** Agent assessment for one company card. Shows nothing when no agent result exists. */
export function AgentNotes({ agent }: { agent?: AgentAssessment | null }) {
  const [open, setOpen] = useState(false)
  if (!agent) return null
  const hasDetail = agent.evidence.length > 0 || agent.reasons.length > 0 || agent.summary
  return <div className="agent-notes">
    <div className="agent-notes-head">
      <span><Sparkles size={13} /> 에이전트 {agent.score != null ? `적합도 ${Math.round(agent.score)}점` : '검토'}</span>
      {agent.source === 'rule_based' && <small>기본 규칙</small>}
      {hasDetail && <button type="button" className="link-button" onClick={event => { event.stopPropagation(); setOpen(!open) }}>{open ? '접기' : '근거 보기'}</button>}
    </div>
    {agent.warnings.map(warning => <p className="agent-warning" key={warning}><CircleAlert size={13} /> {warning}</p>)}
    {open && <>
      {agent.summary && <p className="agent-summary">{agent.summary}</p>}
      {agent.reasons.length > 0 && <p className="agent-summary">{agent.reasons.join(' · ')}</p>}
      <EvidenceList evidence={agent.evidence} />
    </>}
  </div>
}

/** '에이전트 검토' card for a saved request: legal status, evidence, unknowns. */
export function RequestReviewCard({ review, loading, error }: { review: RequestAssessment | null; loading: boolean; error: string }) {
  return <section className="match-card agent-review-card" aria-label="에이전트 검토">
    <div className="match-card-head"><h2><Sparkles size={16} /> 에이전트 검토</h2>{review && <span>{review.source === 'rule_based' ? '기본 규칙' : review.source}</span>}</div>
    {loading ? <p className="match-muted">검토 결과를 불러오는 중입니다…</p>
      : error ? <p className="match-error" role="alert">{error}</p>
      : review && <>
        <dl className="agent-review-status">
          <div><dt>법적 지위</dt><dd>{review.legal_status ?? <span className="unverified">확인되지 않음</span>}</dd></div>
        </dl>
        {review.summary && <p className="agent-summary">{review.summary}</p>}
        {review.warnings.map(warning => <p className="agent-warning" key={warning}><CircleAlert size={13} /> {warning}</p>)}
        <EvidenceList evidence={review.evidence} />
        {review.missing_fields.length > 0 && <p className="match-muted"><strong>보완하면 좋은 항목</strong> {review.missing_fields.join(', ')}</p>}
        {review.unverified.length > 0 && <div className="agent-unverified">
          <strong>아직 확인되지 않은 것</strong>
          <ul>{review.unverified.map(item => <li key={item}>{item}</li>)}</ul>
        </div>}
      </>}
  </section>
}
