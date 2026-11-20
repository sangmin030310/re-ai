import { useState } from 'react'
import { ArrowLeft, ArrowRight, Building2, Check, MapPin, MessageSquare, Navigation, Search, Truck } from 'lucide-react'
import type { Company, IntakeRequest } from './lib/api'
import { AgentNotes, km, TrustBadge, TrustStats } from './ui'

const localRegion = (region: string) => region.replace(/[시군]$/, '')
const isExcluded = (company: Company) => Boolean(company.match?.unmet.length)

export default function CompanyMarket({
  companies, request, selected, busy, onContact, hasContact, onNavigate, picked, onTogglePick,
}: {
  companies: Company[]
  request: IntakeRequest
  selected: string | null
  busy: boolean
  onContact: (company: Company) => void
  hasContact: (id: string) => boolean
  onNavigate: () => void
  picked?: Set<string>
  onTogglePick?: (company: Company) => void
}) {
  const [query, setQuery] = useState('')
  const [transport, setTransport] = useState('')
  const [sort, setSort] = useState('recommended')
  const [detail, setDetail] = useState<Company | null>(null)
  const [showExcluded, setShowExcluded] = useState(false)
  const region = localRegion(request.region)
  const sameRegion = (company: Company) => Number(company.city === region)
  const pickup = (company: Company) => Number(company.transport === '업체 수거')
  const filtered = companies.filter(company => (
    (!transport || company.transport === transport)
    && `${company.name} ${company.city} ${company.route}`.toLowerCase().includes(query.trim().toLowerCase())
  ))
  const distance = (company: Company) => company.distance_km ?? Number.POSITIVE_INFINITY
  const score = (company: Company) => company.agent?.score ?? -1
  filtered.sort((a, b) => sort === 'capacity' ? b.max_ton - a.max_ton
    : sort === 'distance' ? distance(a) - distance(b)
    : Number(b.registered) - Number(a.registered) || score(b) - score(a) || sameRegion(b) - sameRegion(a)
      || pickup(b) - pickup(a) || distance(a) - distance(b))
  const canPick = (company: Company) => Boolean(onTogglePick && company.inquiry_available && !hasContact(company.id))
  const recommended = filtered.filter(company => !isExcluded(company))
  const excluded = filtered.filter(isExcluded)

  function openDetail(company: Company) {
    onNavigate()
    setDetail(company)
  }

  function contactButton(company: Company, fromList = false) {
    return <button className={fromList ? 'subtle-button' : 'primary-button'} type="button" disabled={busy} onClick={() => {
      if (fromList) openDetail(company)
      onContact(company)
    }}>
      <MessageSquare size={16} /> {hasContact(company.id) ? '대화 열기' : '반입 기준 문의하기'}
    </button>
  }

  function card(company: Company) {
    const blocked = isExcluded(company)
    return <article className={`market-list-card ${picked?.has(company.id) ? 'picked' : ''}`} key={company.id}>
      {canPick(company) && <label className="market-pick" title="여러 업체에 한 번에 문의할 목록에 담기">
        <input type="checkbox" checked={picked?.has(company.id) ?? false} disabled={busy} onChange={() => onTogglePick?.(company)} />
        <span>한 번에 문의</span>
      </label>}
      <button className="market-item" onClick={() => openDetail(company)} disabled={busy}>
        <span className="market-symbol"><Building2 size={24} /></span>
        <span className="market-item-info">
          <span className="market-item-name">{company.name} {!blocked && selected === company.id && <span className="market-selected"><Check size={13} /> 선택한 업체</span>}</span>
          <span className="market-item-description">{company.city} · {company.route}</span>
          <span className="market-trust-line"><TrustBadge trust={company.trust} compact /><TrustStats trust={company.trust} /></span>
          <span className={blocked ? 'market-unmet' : 'market-match-summary'}>
            <strong>{blocked ? '조건 미충족' : '추천 이유'}</strong> {blocked ? company.match?.unmet.join(' ') : company.match?.matched.join(' · ')}
          </span>
          {!blocked && <span className="market-item-description"><strong>추가 확인</strong> {company.check}</span>}
          <span className="market-tags">
            <span><Truck size={14} /> {company.transport}</span>
            {km(company.distance_km) && <span><Navigation size={13} /> {km(company.distance_km)}</span>}
            <span>월 최대 {company.max_ton}톤</span>
            {company.trust?.price_model && <span>{company.trust.price_model}</span>}
            <span className={company.inquiry_available ? 'market-tag-contact' : 'market-tag-preview'}>
              {company.inquiry_available ? '문의 가능' : company.registered ? '등록 업체' : '비교용 예시'}
            </span>
          </span>
        </span>
        <ArrowRight size={19} className="market-arrow" aria-hidden="true" />
      </button>
      {!blocked && <AgentNotes agent={company.agent} />}
      {company.inquiry_available && <div className="market-card-contact">{contactButton(company, true)}</div>}
    </article>
  }

  return <section className="market-body" aria-label="업체 둘러보기">
    {detail ? <>
      <button className="subtle-button market-back" disabled={busy} onClick={() => { onNavigate(); setDetail(null) }}><ArrowLeft size={16} /> 업체 목록</button>
      <article className="match-card market-details">
        <div className="market-detail-heading">
          <span className="market-symbol"><Building2 size={28} /></span>
          <div><h2>{detail.name}</h2><p><MapPin size={15} /> {detail.city} · {detail.route}</p></div>
          {!isExcluded(detail) && selected === detail.id && <span className="market-selected"><Check size={15} /> 선택한 업체</span>}
        </div>
        <p>{detail.intro}</p>
        <dl className="market-properties">
          <div><dt>이동 목적지</dt><dd>{detail.city} · {detail.name}{km(detail.distance_km) ? ` (${km(detail.distance_km)}, 직선거리)` : ''}</dd></div>
          <div><dt>허가</dt><dd><TrustBadge trust={detail.trust} />{detail.trust?.permit_number && <small className="trust-detail"> 허가번호 {detail.trust.permit_number}{detail.trust.permit_valid_until ? ` · ${detail.trust.permit_valid_until}까지` : ''}</small>}</dd></div>
          <div><dt>활동</dt><dd><TrustStats trust={detail.trust} /></dd></div>
          {detail.trust?.price_model && <div><dt>거래 방식</dt><dd>{detail.trust.price_model}</dd></div>}
          <div><dt>운반 방식</dt><dd>{detail.transport}</dd></div>
          <div><dt>취급 재질</dt><dd>{detail.materials.join(' · ')}</dd></div>
          <div><dt>수거·반입 대상 지역</dt><dd>{detail.regions.join(' · ')}</dd></div>
          {detail.min_ton != null && <div><dt>월 최소 반입량</dt><dd>{detail.min_ton}톤</dd></div>}
          <div><dt>월 수용량</dt><dd>최대 {detail.max_ton}톤</dd></div>
          <div><dt>오염 상태 (배출업체 입력)</dt><dd>{request.contamination}</dd></div>
          <div><dt>추가 확인 사항</dt><dd>{detail.check}</dd></div>
        </dl>
        {isExcluded(detail) ? <p className="market-unmet"><strong>조건 미충족</strong> {detail.match?.unmet.join(' ')}</p>
          : <p className="market-reason"><Check size={17} /> {detail.match?.matched.join(' · ')}</p>}
        {!isExcluded(detail) && <AgentNotes agent={detail.agent} />}
        {detail.inquiry_available ? <div className="market-detail-actions">{contactButton(detail)}</div>
          : !detail.registered && !isExcluded(detail) && <p className="market-contact-note">조건 비교용 예시 업체입니다.</p>}
      </article>
    </> : <>
      <div className="market-toolbar">
        <label className="market-search"><Search size={18} /><input aria-label="업체 검색" placeholder="업체 이름, 지역, 처리 방식 검색" value={query} onChange={e => setQuery(e.target.value)} /></label>
        <label><span>운반 방식</span><select value={transport} onChange={e => setTransport(e.target.value)}>
          <option value="">전체</option><option>업체 수거</option><option>배출업체 직접 운반</option>
        </select></label>
        <label><span>정렬</span><select value={sort} onChange={e => setSort(e.target.value)}>
          <option value="recommended">추천순</option><option value="distance">가까운 순</option><option value="capacity">월 수용량 많은 순</option>
        </select></label>
      </div>
      <div className="market-results"><h2>추천 업체 {recommended.length}곳</h2></div>
      {recommended.length ? <div className="market-list">{recommended.map(card)}</div>
        : <p className="market-empty">{filtered.length || !companies.length
          ? '현재 재질·지역·물량 조건에 맞는 업체가 없습니다.'
          : '검색어 또는 운반 방식에 맞는 업체가 없습니다.'}</p>}
      {excluded.length > 0 && <>
        <button className="subtle-button market-excluded-toggle" onClick={() => setShowExcluded(!showExcluded)} aria-expanded={showExcluded}>
          조건이 맞지 않은 업체 {excluded.length}곳 {showExcluded ? '접기' : '보기'}
        </button>
        {showExcluded && <div className="market-list">{excluded.map(card)}</div>}
      </>}
    </>}
  </section>
}
