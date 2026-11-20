import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import {
  ArrowDownToLine, Check, CircleAlert, ClipboardCheck, FileUp, Handshake, History, MapPin, MessageSquare,
  Paperclip, Send, Truck, X,
} from 'lucide-react'
import {
  api, frequencies, newClientId,
  type CarrierCandidate, type ChecklistItem, type CompanyRole, type Deal, type DealSummary, type DealTerms,
  type PriceType, type Shipment, type TransportBy,
} from './lib/api'
import { dateTime, errorText, km, priceSummary, tons, TrustBadge, TrustStats, won } from './ui'
import './deals.css'

const roleNames: Record<string, string> = {
  supplier: '배출업체', recycler: '가공업체', carrier: '운송업체', carrier_candidate: '운송 견적 요청 받음', any: '누구나',
}
const stageNames = { before_agreement: '합의 전', before_transport: '운송 전', after_delivery: '반입 후' }
const shipmentFields: [keyof Shipment, string, string, CompanyRole[]][] = [
  ['pickup_address', '상차 주소', '예: 전주시 덕진구 ○○로 12, 2번 출입구', ['supplier']],
  ['pickup_window', '상차 가능 시간', '예: 12/3(수) 09:00–12:00', ['supplier', 'carrier']],
  ['pickup_equipment', '상차 장비', '예: 지게차 있음 / 수작업', ['supplier']],
  ['packaging', '포장 상태', '예: 톤백 4개', ['supplier']],
  ['dropoff_address', '하차 주소', '가공시설 주소', ['recycler']],
  ['dropoff_window', '반입 가능 시간', '예: 평일 13:00–17:00', ['recycler']],
  ['unloading', '하차 조건', '예: 계량 후 하차, 지게차 지원', ['recycler']],
  ['vehicle', '배차 차량', '예: 5톤 윙바디', ['carrier']],
  ['driver_contact', '기사 연락처', '예: 010-0000-0000', ['carrier']],
]

export function DealsPage({ workspace, role, selectedId, onSelect, onOpenInquiry }: {
  workspace: string
  role: CompanyRole
  selectedId: string | null
  onSelect: (id: string | null) => void
  onOpenInquiry: (id: string) => void
}) {
  const [items, setItems] = useState<DealSummary[] | null>(null)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState<'open' | 'mine' | 'done'>('open')

  useEffect(() => {
    let ignore = false
    const load = () => api.deals().then(result => { if (!ignore) { setItems(result); setError('') } },
      failure => { if (!ignore) setError(errorText(failure)) })
    void load()
    const timer = window.setInterval(load, 5000)
    return () => { ignore = true; window.clearInterval(timer) }
  }, [])

  const shown = (items ?? []).filter(item => filter === 'done' ? ['completed', 'cancelled'].includes(item.status)
    : filter === 'mine' ? item.next_action.mine : !['completed', 'cancelled'].includes(item.status))
  const mineCount = (items ?? []).filter(item => item.next_action.mine).length

  return <section className="match-page deals-page">
    <header className="match-heading">
      <h1>거래 건</h1>
      <p>{role === 'carrier' ? '받은 운송 견적 요청과 맡은 운송 건입니다. 상차·하차 조건을 확인하고 진행 상황을 기록하세요.'
        : '조건 합의부터 운송, 반입·계량, 서류까지 세 업체가 같은 화면을 보며 진행합니다.'}</p>
    </header>
    {error && <p className="match-error" role="alert">{error}</p>}
    <div className="deals-grid">
      <section className="match-card deal-list" aria-label="거래 목록">
        <div className="deal-filters" role="tablist">
          {([['open', '진행 중'], ['mine', `내 차례${mineCount ? ` ${mineCount}` : ''}`], ['done', '완료·취소']] as const).map(([key, label]) =>
            <button key={key} role="tab" aria-selected={filter === key} className={filter === key ? 'active' : ''} onClick={() => setFilter(key)}>{label}</button>)}
        </div>
        {!items ? <p className="match-muted">거래 건을 불러오는 중입니다…</p>
          : !shown.length ? <p className="match-muted">{filter === 'mine' ? '지금 처리할 일이 없습니다.' : '표시할 거래 건이 없습니다.'}
            {role !== 'carrier' && filter === 'open' && <> 기업 문의함의 대화에서 <strong>거래 건 만들기</strong>로 시작하세요.</>}</p>
          : shown.map(item => <button key={item.id} className={`deal-list-item ${selectedId === item.id ? 'chosen' : ''}`} onClick={() => onSelect(item.id)}>
            <span className="deal-list-title"><strong>{item.material} {tons(item.quantity_ton)}</strong><span className={`deal-status ${item.status}`}>{item.status_label}</span></span>
            <span className="match-muted">{item.supplier_name} → {item.recycler_name}{item.carrier_name ? ` · 운송 ${item.carrier_name}` : ''}</span>
            <span className="match-muted">{item.route}</span>
            <span className={`deal-next ${item.next_action.mine ? 'mine' : ''}`}>{item.next_action.mine && <CircleAlert size={13} />} {item.next_action.label}</span>
          </button>)}
      </section>
      {selectedId ? <DealDetail key={selectedId} dealId={selectedId} workspace={workspace} onOpenInquiry={onOpenInquiry} onClose={() => onSelect(null)} />
        : <section className="match-card match-empty"><Handshake size={28} /><p>목록에서 거래 건을 선택하세요.</p></section>}
    </div>
  </section>
}

function Card({ title, icon, children, extra }: { title: string; icon?: ReactNode; children: ReactNode; extra?: ReactNode }) {
  return <section className="match-card deal-card"><div className="match-card-head"><h2>{icon} {title}</h2>{extra}</div>{children}</section>
}

function DealDetail({ dealId, workspace, onOpenInquiry, onClose }: {
  dealId: string
  workspace: string
  onOpenInquiry: (id: string) => void
  onClose: () => void
}) {
  const [deal, setDeal] = useState<Deal | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let ignore = false
    const load = () => api.deal(dealId).then(result => { if (!ignore) setDeal(result) }, failure => { if (!ignore) setError(errorText(failure)) })
    void load()
    const timer = window.setInterval(load, 3000)
    return () => { ignore = true; window.clearInterval(timer) }
  }, [dealId])

  async function run(action: () => Promise<Deal | unknown>) {
    if (busy) return false
    setBusy(true)
    setError('')
    try {
      const result = await action()
      if (result && typeof result === 'object' && 'status' in result && 'flow' in result) setDeal(result as Deal)
      else setDeal(await api.deal(dealId))
      return true
    } catch (failure) {
      setError(errorText(failure))
      return false
    } finally {
      setBusy(false)
    }
  }

  if (!deal) return <section className="match-card">{error ? <p className="match-error" role="alert">{error}</p> : <p className="match-muted">거래 건을 불러오는 중입니다…</p>}</section>

  const role = deal.my_role
  const party = role === 'supplier' || role === 'recycler'
  const flowIndex = deal.flow.findIndex(step => step.status === deal.status)
  const cancellable = party && ['negotiating', 'agreed', 'transport_pending', 'scheduled'].includes(deal.status)

  return <div className="deal-detail">
    <section className="match-card deal-header">
      <div className="match-card-head">
        <h2>{deal.request.material} {tons(deal.terms?.quantity_ton ?? deal.request.monthly_ton)} · {deal.request.region} → {deal.destination_city ?? '가공업체'}</h2>
        <button type="button" className="icon-btn" aria-label="거래 건 닫기" onClick={onClose}><X size={18} /></button>
      </div>
      <div className="deal-parties">
        {(['supplier', 'recycler', 'carrier'] as const).map(key => {
          const item = deal.parties[key]
          return <div key={key} className={`deal-party ${role === key ? 'me' : ''}`}>
            <small>{roleNames[key]}{role === key ? ' · 나' : ''}</small>
            <strong>{item?.name ?? (key === 'carrier' ? (deal.needs_carrier ? '선정 전' : '자체 운반') : '—')}</strong>
            {item && <><TrustBadge trust={item.trust} compact /><TrustStats trust={item.trust} /></>}
          </div>
        })}
      </div>
      {deal.status === 'cancelled' ? <p className="match-error">취소된 거래입니다. 사유: {deal.cancel_reason}</p>
        : <ol className="deal-steps">{deal.flow.map((step, index) => <li key={step.status}
          className={index < flowIndex ? 'done' : index === flowIndex ? 'current' : ''}>
          <span>{index < flowIndex ? <Check size={12} strokeWidth={3} /> : index + 1}</span>{step.label}
        </li>)}</ol>}
      <p className={`deal-next-banner ${deal.next_action.mine ? 'mine' : ''}`} role="status">
        {deal.next_action.mine ? <CircleAlert size={16} /> : <History size={16} />} {deal.next_action.mine ? '내 차례 · ' : ''}{deal.next_action.label}
      </p>
      {error && <p className="match-error" role="alert">{error}</p>}
      {deal.source_inquiry_id && <button type="button" className="link-button" onClick={() => onOpenInquiry(deal.source_inquiry_id!)}>처음 문의 대화 보기</button>}
    </section>

    <Card title="배출 정보" icon={<MapPin size={16} />} extra={km(deal.distance_km) && <span>직선거리 {km(deal.distance_km)}</span>}>
      <dl className="deal-facts">
        <div><dt>재질</dt><dd>{deal.request.material}</dd></div>
        <div><dt>요청서 월 발생량</dt><dd>{tons(deal.request.monthly_ton)}</dd></div>
        <div><dt>배출 지역</dt><dd>{deal.request.region}</dd></div>
        <div><dt>오염 상태</dt><dd>{deal.request.contamination}</dd></div>
        <div><dt>포장 상태</dt><dd>{deal.request.packaging}</dd></div>
        {deal.request.legal_status && <div><dt>법적 지위</dt><dd>{deal.request.legal_status === '확인 전' ? <span className="unverified">확인되지 않음</span> : `${deal.request.legal_status} (배출업체 입력)`}</dd></div>}
      </dl>
      {deal.request_files.length > 0 && <div className="inbox-attachment">{deal.request_files.map(file =>
        <button type="button" key={file.id} className="subtle-button" onClick={() => void api.downloadDealRequestFile(deal.id, file).catch(failure => setError(errorText(failure)))}>
          <Paperclip size={14} /> {file.name}</button>)}</div>}
    </Card>

    <TermsCard deal={deal} busy={busy} run={run} />
    <TransportCard deal={deal} busy={busy} run={run} />
    <ShipmentCard deal={deal} busy={busy} run={run} />
    <ChecklistCard deal={deal} busy={busy} run={run} />
    {deal.can_chat && <DealChat deal={deal} workspace={workspace} onSent={() => void api.deal(deal.id).then(setDeal)} />}
    {deal.events.length > 0 && <Card title="진행 기록" icon={<History size={16} />}>
      <ol className="deal-timeline">{deal.events.slice().reverse().map(event => <li key={event.sequence}>
        <small>{dateTime(event.created_at)} · {event.actor_name}</small><p>{event.detail}</p>
      </li>)}</ol>
    </Card>}
    {cancellable && <CancelDeal busy={busy} onCancel={reason => run(() => api.cancelDeal(deal.id, reason))} />}
  </div>
}

type Runner = (action: () => Promise<unknown>) => Promise<boolean>

function TermsCard({ deal, busy, run }: { deal: Deal; busy: boolean; run: Runner }) {
  const party = deal.my_role === 'supplier' || deal.my_role === 'recycler'
  const editable = party && ['negotiating', 'agreed'].includes(deal.status)
  const base = deal.terms ?? deal.suggested_terms ?? {}
  const [open, setOpen] = useState(!deal.terms && editable)
  const [form, setForm] = useState({
    price_type: (base.price_type ?? '') as PriceType | '',
    unit_price: base.unit_price?.toString() ?? '',
    quantity_ton: base.quantity_ton?.toString() ?? deal.request.monthly_ton?.toString() ?? '',
    frequency: base.frequency ?? '매월 정기',
    start_date: base.start_date ?? '',
    transport_by: (base.transport_by ?? '') as TransportBy | '',
    notes: base.notes ?? '',
  })
  const terms = deal.terms

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!form.price_type || !form.transport_by) return
    const body: DealTerms = {
      price_type: form.price_type, unit_price: form.price_type === '무상' ? null : Number(form.unit_price),
      quantity_ton: Number(form.quantity_ton), frequency: form.frequency as DealTerms['frequency'],
      start_date: form.start_date || null, transport_by: form.transport_by, notes: form.notes,
    }
    if (await run(() => api.proposeTerms(deal.id, body))) setOpen(false)
  }

  return <Card title="거래 조건" icon={<Handshake size={16} />} extra={terms && <span>{deal.terms_agreed_at ? `합의 ${dateTime(deal.terms_agreed_at)}` : deal.terms_proposed_by_me ? '내가 제안 · 상대 확인 대기' : '상대가 제안'}</span>}>
    {terms ? <dl className="deal-facts">
      {terms.price_type && <div><dt>대금</dt><dd>{priceSummary(terms.price_type, terms.unit_price)}<small> {deal.labels.price[terms.price_type]}</small></dd></div>}
      {terms.price_type && terms.price_type !== '무상' && terms.unit_price != null && terms.quantity_ton &&
        <div><dt>회당 예상 금액</dt><dd>{won(Math.round(terms.unit_price * terms.quantity_ton))}</dd></div>}
      <div><dt>물량</dt><dd>{tons(terms.quantity_ton)} · {terms.frequency}</dd></div>
      {terms.start_date && <div><dt>시작일</dt><dd>{terms.start_date}</dd></div>}
      {terms.transport_by && <div><dt>운송 담당</dt><dd>{deal.labels.transport[terms.transport_by]}</dd></div>}
      {terms.notes && <div><dt>메모</dt><dd>{terms.notes}</dd></div>}
    </dl> : <p className="match-muted">아직 제안된 조건이 없습니다.{deal.suggested_terms?.price_type && ' 가공업체가 문의에 남긴 견적을 초안으로 채워 두었습니다.'}</p>}
    {party && deal.status === 'negotiating' && terms && !deal.terms_proposed_by_me && <div className="inbox-attachment">
      <button type="button" className="primary-button" disabled={busy} onClick={() => void run(() => api.acceptTerms(deal.id))}><Check size={15} /> 이 조건으로 합의</button>
      <button type="button" className="subtle-button" disabled={busy} onClick={() => setOpen(true)}>수정해서 다시 제안</button>
    </div>}
    {editable && !open && (deal.terms_proposed_by_me || deal.status === 'agreed' || !terms) &&
      <button type="button" className="subtle-button" onClick={() => setOpen(true)}>{terms ? '조건 수정 제안' : '조건 제안하기'}</button>}
    {editable && deal.status === 'agreed' && open && <p className="match-muted">합의 후 조건을 바꾸면 상대 업체가 다시 수락해야 합니다.</p>}
    {editable && open && <form className="match-form deal-form" onSubmit={submit}>
      <fieldset disabled={busy}>
        <div className="match-fields">
          <label>대금 방식<select required value={form.price_type} onChange={event => setForm({ ...form, price_type: event.target.value as PriceType })}>
            <option value="" disabled>선택</option>
            <option value="매입">매입 — 가공업체가 배출업체에 지급</option>
            <option value="처리비">처리비 — 배출업체가 가공업체에 지급</option>
            <option value="무상">무상</option>
          </select></label>
          <label>톤당 단가(원)<input type="number" min="0" step="1000" required={form.price_type !== '무상'} disabled={form.price_type === '무상'}
            value={form.unit_price} onChange={event => setForm({ ...form, unit_price: event.target.value })} /></label>
          <label>회당 물량(톤)<input type="number" min="0.001" step="any" required value={form.quantity_ton} onChange={event => setForm({ ...form, quantity_ton: event.target.value })} /></label>
          <label>주기<select value={form.frequency} onChange={event => setForm({ ...form, frequency: event.target.value as DealTerms['frequency'] })}>
            {frequencies.map(item => <option key={item}>{item}</option>)}
          </select></label>
          <label>시작일<input type="date" value={form.start_date} onChange={event => setForm({ ...form, start_date: event.target.value })} /></label>
          <label>운송 담당<select required value={form.transport_by} onChange={event => setForm({ ...form, transport_by: event.target.value as TransportBy })}>
            <option value="" disabled>선택</option>
            {Object.entries(deal.labels.transport).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select></label>
        </div>
        <label><span className="field-title">메모 <small>선택</small></span><textarea rows={2} maxLength={500} value={form.notes} onChange={event => setForm({ ...form, notes: event.target.value })} /></label>
        <div className="inbox-attachment">
          <button type="submit" className="primary-button" disabled={!form.price_type || !form.transport_by}><Send size={15} /> 조건 제안</button>
          {terms && <button type="button" className="subtle-button" onClick={() => setOpen(false)}>취소</button>}
        </div>
      </fieldset>
    </form>}
  </Card>
}

function TransportCard({ deal, busy, run }: { deal: Deal; busy: boolean; run: Runner }) {
  const owner = deal.transport_owner === deal.my_role
  const [carriers, setCarriers] = useState<CarrierCandidate[] | null>(null)
  const [picked, setPicked] = useState<string[]>([])
  const [note, setNote] = useState('')
  const [quote, setQuote] = useState({ price: '', available_date: '', vehicle: '', note: '' })
  const asking = owner && deal.needs_carrier && ['agreed', 'transport_pending'].includes(deal.status)

  useEffect(() => {
    if (!asking) return
    let ignore = false
    api.carriers(deal.id).then(result => { if (!ignore) setCarriers(result) }, () => { if (!ignore) setCarriers([]) })
    return () => { ignore = true }
  }, [asking, deal.id, deal.transport_requests.length])

  if (!deal.terms?.transport_by) return null
  if (!deal.needs_carrier) return <Card title="운송" icon={<Truck size={16} />}>
    <p className="match-muted">{deal.labels.transport[deal.terms.transport_by]} 방식입니다. 운송 건 정보에 상차 시간을 적고 {owner ? '일정을 확정하세요.' : '담당 업체가 일정을 확정합니다.'}</p>
    {owner && deal.status === 'agreed' && <button type="button" className="primary-button" disabled={busy || !deal.shipment.pickup_window}
      onClick={() => void run(() => api.progress(deal.id, 'scheduled'))}><Check size={15} /> 운송 일정 확정</button>}
  </Card>

  const mine = deal.transport_requests.find(item => item.carrier_id && deal.my_role === 'carrier_candidate')
  const statusNames = { requested: '견적 대기', quoted: '견적 도착', declined: '거절', selected: '선정', not_selected: '미선정' }

  return <Card title="운송업체 견적" icon={<Truck size={16} />} extra={<span>{deal.labels.transport[deal.terms.transport_by]}</span>}>
    {deal.my_role === 'carrier_candidate' && mine ? <>
      <p className="match-muted">요청 메모: {mine.note || '없음'} · 상태: <strong>{statusNames[mine.status]}</strong></p>
      {mine.quote && <p>보낸 견적: {won(mine.quote.price)} · {mine.quote.available_date} 가능 · {mine.quote.vehicle}</p>}
      {deal.status === 'transport_pending' && ['requested', 'quoted'].includes(mine.status) && <form className="match-form deal-form" onSubmit={event => {
        event.preventDefault()
        void run(() => api.respondTransport(deal.id, { action: 'quote', price: Number(quote.price), available_date: quote.available_date, vehicle: quote.vehicle, note: quote.note }))
      }}>
        <fieldset disabled={busy}>
          <div className="match-fields">
            <label>운송비(원, 1회)<input type="number" min="0" step="1000" required value={quote.price} onChange={event => setQuote({ ...quote, price: event.target.value })} /></label>
            <label>가능한 날짜<input type="date" required value={quote.available_date} onChange={event => setQuote({ ...quote, available_date: event.target.value })} /></label>
            <label>차량<input placeholder="예: 5톤 윙바디" maxLength={200} value={quote.vehicle} onChange={event => setQuote({ ...quote, vehicle: event.target.value })} /></label>
            <label>메모<input maxLength={500} value={quote.note} onChange={event => setQuote({ ...quote, note: event.target.value })} /></label>
          </div>
          <div className="inbox-attachment">
            <button type="submit" className="primary-button"><Send size={15} /> {mine.quote ? '견적 수정' : '견적 보내기'}</button>
            <button type="button" className="subtle-button" onClick={() => void run(() => api.respondTransport(deal.id, { action: 'decline' }))}>이번 건은 어려워요</button>
          </div>
        </fieldset>
      </form>}
    </> : <>
      {deal.transport_requests.length > 0 && <div className="table-scroll"><table className="compare-table">
        <thead><tr><th>운송업체</th><th>허가</th><th>상태</th><th>운송비</th><th>가능일</th><th>차량</th><th /></tr></thead>
        <tbody>{deal.transport_requests.map(item => <tr key={item.id} className={item.status === 'selected' ? 'selected' : ''}>
          <td><strong>{item.carrier_name}</strong>{item.quote?.note && <small>{item.quote.note}</small>}</td>
          <td><TrustBadge trust={item.trust} compact /></td>
          <td>{statusNames[item.status]}</td>
          <td>{item.quote ? won(item.quote.price) : '—'}</td>
          <td>{item.quote?.available_date ?? '—'}</td>
          <td>{item.quote?.vehicle || '—'}</td>
          <td>{owner && deal.status === 'transport_pending' && item.status === 'quoted' &&
            <button type="button" className="primary-button" disabled={busy} onClick={() => void run(() => api.selectTransport(deal.id, item.id))}>선택</button>}</td>
        </tr>)}</tbody>
      </table></div>}
      {asking && !(carriers && carriers.length && carriers.every(item => item.requested)) && <form className="match-form deal-form" onSubmit={event => {
        event.preventDefault()
        if (picked.length) void run(() => api.requestTransport(deal.id, picked, note)).then(ok => { if (ok) setPicked([]) })
      }}>
        <h3>{deal.transport_requests.length ? '운송업체 추가 요청' : '견적 요청할 운송업체'}</h3>
        {!carriers ? <p className="match-muted">운송업체를 찾는 중입니다…</p>
          : !carriers.filter(item => !item.requested).length ? <p className="match-muted">{carriers.length ? '조건에 맞는 운송업체에 모두 요청했습니다.' : '출발지·도착지와 재질·물량 조건에 맞는 가입 운송업체가 없습니다.'}</p>
          : <ul className="carrier-picks">{carriers.filter(item => !item.requested).map(item => <li key={item.id}><label>
            <input type="checkbox" checked={picked.includes(item.id)} onChange={() => setPicked(previous => previous.includes(item.id) ? previous.filter(id => id !== item.id) : [...previous, item.id])} />
            <span><strong>{item.name}</strong> <small>{item.city} · 월 최대 {item.max_ton}톤 · {item.regions.join(', ')}</small></span>
            <TrustBadge trust={item.trust} compact />
          </label></li>)}</ul>}
        {carriers && carriers.some(item => !item.requested) && <>
          <label><span className="field-title">요청 메모 <small>선택</small></span><input maxLength={500} placeholder="예: 다음 주 화·수 오전 상차 희망" value={note} onChange={event => setNote(event.target.value)} /></label>
          <button type="submit" className="primary-button" disabled={busy || !picked.length}><Truck size={15} /> {picked.length || ''}곳에 견적 요청</button>
        </>}
      </form>}
      {!owner && deal.needs_carrier && deal.status === 'agreed' && <p className="match-muted">운송 담당 업체가 운송업체에 견적을 요청합니다.</p>}
    </>}
  </Card>
}

function ShipmentCard({ deal, busy, run }: { deal: Deal; busy: boolean; run: Runner }) {
  const role = deal.my_role
  const participant = role === 'supplier' || role === 'recycler' || role === 'carrier'
  const editable = participant && !['delivered', 'completed', 'cancelled'].includes(deal.status)
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<Shipment>(deal.shipment)
  const [actual, setActual] = useState('')
  const mover = deal.parties.carrier ? 'carrier' : deal.transport_owner
  const pendingDocs = deal.checklist.filter(item => item.state === 'pending').length

  function save(event: FormEvent) {
    event.preventDefault()
    const changes = Object.fromEntries(shipmentFields.map(([key]) => [key, (form[key] as string | null | undefined)?.toString().trim() || null])
      .filter(([key, value]) => value !== (deal.shipment[key as keyof Shipment] ?? null)))
    if (form.planned_ton !== deal.shipment.planned_ton) changes.planned_ton = form.planned_ton || null
    void run(() => api.updateShipment(deal.id, changes as Shipment)).then(ok => { if (ok) setEditing(false) })
  }

  return <Card title="운송 건" icon={<Truck size={16} />} extra={editable && !editing &&
    <button type="button" className="subtle-button" onClick={() => { setForm(deal.shipment); setEditing(true) }}>정보 입력·수정</button>}>
    {editing ? <form className="match-form deal-form" onSubmit={save}>
      <fieldset disabled={busy}>
        <div className="match-fields">
          {shipmentFields.map(([key, label, placeholder, owners]) => <label key={key}>
            <span className="field-title">{label} <small>{owners.map(owner => roleNames[owner]).join('·')} 입력</small></span>
            <input maxLength={200} placeholder={placeholder} value={(form[key] as string | null | undefined) ?? ''} onChange={event => setForm({ ...form, [key]: event.target.value })} />
          </label>)}
          <label>운송 예정 물량(톤)<input type="number" min="0.001" step="any" value={form.planned_ton ?? ''} onChange={event => setForm({ ...form, planned_ton: event.target.value ? Number(event.target.value) : null })} /></label>
        </div>
        <div className="inbox-attachment">
          <button type="submit" className="primary-button">저장</button>
          <button type="button" className="subtle-button" onClick={() => setEditing(false)}>취소</button>
        </div>
      </fieldset>
    </form> : <dl className="deal-facts shipment-facts">
      <div className="shipment-leg"><dt>출발 · {deal.parties.supplier.name}</dt><dd>
        {deal.shipment.pickup_address || <span className="draft-missing">상차 주소 미입력</span>}<br />
        <small>{deal.shipment.pickup_window || '상차 시간 미정'} · {deal.shipment.pickup_equipment || '장비 미입력'} · {deal.shipment.packaging || '포장 미입력'}</small>
      </dd></div>
      <div className="shipment-leg"><dt>도착 · {deal.parties.recycler.name}</dt><dd>
        {deal.shipment.dropoff_address || <span className="draft-missing">하차 주소 미입력</span>}<br />
        <small>{deal.shipment.dropoff_window || '반입 시간 미정'} · {deal.shipment.unloading || '하차 조건 미입력'}</small>
      </dd></div>
      <div><dt>물량</dt><dd>예정 {tons(deal.shipment.planned_ton ?? deal.terms?.quantity_ton ?? deal.request.monthly_ton)}
        {deal.shipment.picked_up_ton != null && <> · 상차 {tons(deal.shipment.picked_up_ton)}</>}
        {deal.shipment.delivered_ton != null && <> · <strong>계량 {tons(deal.shipment.delivered_ton)}</strong></>}</dd></div>
      <div><dt>차량</dt><dd>{deal.shipment.vehicle || '—'}{deal.shipment.driver_contact && ` · ${deal.shipment.driver_contact}`}</dd></div>
    </dl>}
    <div className="deal-progress">
      {deal.status === 'scheduled' && role === mover && <button type="button" className="primary-button" disabled={busy}
        onClick={() => void run(() => api.progress(deal.id, 'picked_up'))}><Truck size={15} /> 상차 완료 기록</button>}
      {deal.status === 'picked_up' && role === 'recycler' && <form className="inline-form" onSubmit={event => {
        event.preventDefault()
        if (actual) void run(() => api.progress(deal.id, 'delivered', Number(actual)))
      }}>
        <label>계량 물량(톤)<input type="number" min="0.001" step="any" required value={actual} onChange={event => setActual(event.target.value)} /></label>
        <button type="submit" className="primary-button" disabled={busy || !actual}><Check size={15} /> 반입·계량 완료</button>
      </form>}
      {deal.status === 'delivered' && (role === 'supplier' || role === 'recycler') && <>
        <button type="button" className="primary-button" disabled={busy || pendingDocs > 0}
          onClick={() => void run(() => api.progress(deal.id, 'completed'))}><ClipboardCheck size={15} /> 거래 완료</button>
        {pendingDocs > 0 && <span className="match-muted">서류 체크리스트 {pendingDocs}건이 남아 있어 완료할 수 없습니다.</span>}
      </>}
    </div>
  </Card>
}

function ChecklistCard({ deal, busy, run }: { deal: Deal; busy: boolean; run: Runner }) {
  const participant = deal.my_role === 'supplier' || deal.my_role === 'recycler' || deal.my_role === 'carrier'
  const done = deal.checklist.filter(item => item.state !== 'pending').length
  const open = !['completed', 'cancelled'].includes(deal.status)
  if (!participant && deal.my_role !== 'carrier_candidate') return null
  return <Card title="서류 체크리스트" icon={<ClipboardCheck size={16} />} extra={<span>{done}/{deal.checklist.length} 완료</span>}>
    <p className="match-muted">필요한 서류 목록은 매칭 에이전트가 정합니다. 모든 항목이 완료되거나 ‘해당 없음’이어야 거래를 완료할 수 있습니다.</p>
    <ul className="checklist">{deal.checklist.map(item => <ChecklistRow key={item.key} item={item} deal={deal} busy={busy} run={run} editable={participant && open} />)}</ul>
  </Card>
}

function ChecklistRow({ item, deal, busy, run, editable }: { item: ChecklistItem; deal: Deal; busy: boolean; run: Runner; editable: boolean }) {
  const input = useRef<HTMLInputElement>(null)
  return <li className={`checklist-item ${item.state}`}>
    <span className="checklist-mark">{item.state === 'done' ? <Check size={14} strokeWidth={3} /> : item.state === 'not_applicable' ? '—' : ''}</span>
    <div className="checklist-body">
      <strong>{item.label}</strong>
      <small>{roleNames[item.owner]} 준비 · {stageNames[item.stage]}{item.source !== 'rule_based' ? ` · ${item.source}` : ''}</small>
      {item.note && <small>{item.note}</small>}
      {item.state_note && <small>메모: {item.state_note}</small>}
      {item.files.map(file => <button type="button" key={file.id} className="link-button" onClick={() => void api.downloadDealFile(deal.id, file)}>
        <ArrowDownToLine size={13} /> {file.name} <small>({file.uploader_name})</small></button>)}
    </div>
    {editable && <div className="checklist-actions">
      <button type="button" className="subtle-button" disabled={busy} onClick={() => input.current?.click()}><FileUp size={14} /> 파일</button>
      {item.state === 'pending' ? <>
        <button type="button" className="subtle-button" disabled={busy} onClick={() => {
          const note = window.prompt('완료 메모 (예: 올바로시스템 전자인계 등록번호)', '')
          if (note !== null) void run(() => api.updateChecklist(deal.id, item.key, 'done', note))
        }}>완료</button>
        <button type="button" className="subtle-button" disabled={busy} onClick={() => {
          const note = window.prompt('해당 없음 사유', '')
          if (note !== null) void run(() => api.updateChecklist(deal.id, item.key, 'not_applicable', note))
        }}>해당 없음</button>
      </> : <button type="button" className="subtle-button" disabled={busy} onClick={() => void run(() => api.updateChecklist(deal.id, item.key, 'pending'))}>되돌리기</button>}
      <input ref={input} type="file" hidden accept=".pdf,.png,.jpg,.jpeg,.docx,.xlsx,.txt,.csv,.hwp,.hwpx" onChange={event => {
        const file = event.target.files?.[0]
        if (file) void run(() => api.uploadDealFile(deal.id, item.key, file))
        event.target.value = ''
      }} />
    </div>}
  </li>
}

function DealChat({ deal, workspace, onSent }: { deal: Deal; workspace: string; onSent: () => void }) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const retry = useRef<{ content: string; id: string } | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const latest = deal.messages.at(-1)?.sequence
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight }, [latest])

  async function send(event: FormEvent) {
    event.preventDefault()
    const content = draft.trim()
    if (!content || busy) return
    setBusy(true)
    setError('')
    if (retry.current?.content !== content) retry.current = { content, id: newClientId() }
    try {
      await api.dealMessage(deal.id, content, retry.current.id)
      retry.current = null
      setDraft('')
      onSent()
    } catch (failure) {
      setError(errorText(failure))
    } finally {
      setBusy(false)
    }
  }

  const members = [deal.parties.supplier.name, deal.parties.recycler.name, deal.parties.carrier?.name].filter(Boolean).join(' · ')
  return <Card title="거래 대화" icon={<MessageSquare size={16} />} extra={<span>{members}</span>}>
    <div className="inbox-messages deal-messages" ref={box} aria-live="polite">
      {!deal.messages.length && <p className="match-muted">{deal.parties.carrier ? '세 업체가 함께 보는 대화입니다. 상차·반입 일정을 여기서 맞추세요.' : deal.needs_carrier ? '운송업체가 선정되면 이 대화에 함께 참여합니다.' : '두 업체가 함께 보는 대화입니다. 상차·반입 일정을 여기서 맞추세요.'}</p>}
      {deal.messages.map(message => <div className={message.author_id === workspace ? 'outgoing' : ''} key={message.sequence}>
        <small>{message.author_id === workspace ? '나' : message.author_name} · {dateTime(message.created_at)}</small>
        <p>{message.content}</p>
      </div>)}
    </div>
    {error && <p className="match-error" role="alert">{error}</p>}
    <form className="inbox-composer" onSubmit={send}>
      <textarea aria-label="거래 대화 입력" rows={2} maxLength={2000} disabled={busy} value={draft} onChange={event => setDraft(event.target.value)} placeholder="메시지를 입력하세요" />
      <button type="submit" className="primary-button" disabled={busy || !draft.trim()}><Send size={15} /> 보내기</button>
    </form>
  </Card>
}

function CancelDeal({ busy, onCancel }: { busy: boolean; onCancel: (reason: string) => Promise<boolean> }) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  return <div className="deal-cancel">
    {open ? <form className="inline-form" onSubmit={event => { event.preventDefault(); if (reason.trim()) void onCancel(reason.trim()) }}>
      <label>취소 사유<input required maxLength={300} value={reason} onChange={event => setReason(event.target.value)} /></label>
      <button type="submit" className="subtle-button danger" disabled={busy || !reason.trim()}>거래 취소</button>
      <button type="button" className="subtle-button" onClick={() => setOpen(false)}>닫기</button>
    </form> : <button type="button" className="link-button danger" onClick={() => setOpen(true)}>거래 취소하기</button>}
  </div>
}
