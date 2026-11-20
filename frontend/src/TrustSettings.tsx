import { useEffect, useState, type FormEvent } from 'react'
import { BadgeCheck, ShieldCheck } from 'lucide-react'
import { api, type CompanyRole, type OperatorCompany, type Trust, type TrustDetails } from './lib/api'
import { errorText, TrustBadge, TrustStats } from './ui'
import './deals.css'

const empty: TrustDetails = { business_number: '', address: '', permit_type: '', permit_number: '', permit_valid_until: null, price_model: '' }
const roleNames: Record<CompanyRole, string> = { supplier: '배출업체', recycler: '가공업체', carrier: '운송업체' }

/** Company permit form, shown inside account settings. */
export function TrustForm({ role }: { role: CompanyRole }) {
  const [form, setForm] = useState<TrustDetails | null>(null)
  const [trust, setTrust] = useState<Trust | null>(null)
  const [types, setTypes] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    api.myTrust().then(result => { setForm({ ...empty, ...result.details }); setTrust(result.trust); setTypes(result.permit_types) },
      failure => setMessage(errorText(failure)))
  }, [])

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!form || busy) return
    setBusy(true)
    setMessage('')
    try {
      const result = await api.saveTrust({ ...form, permit_valid_until: form.permit_valid_until || null })
      setTrust(result.trust)
      setMessage(result.trust.permit_verified ? '저장했습니다.' : '저장했습니다. 허가 정보는 운영자가 확인하면 배지가 표시됩니다.')
    } catch (failure) {
      setMessage(errorText(failure))
    } finally {
      setBusy(false)
    }
  }

  if (!form) return message ? <p className="match-error">{message}</p> : null
  const set = (patch: Partial<TrustDetails>) => setForm({ ...form, ...patch })
  return <form className="match-form trust-form" onSubmit={save}>
    <h3><ShieldCheck size={16} /> 업체 신뢰 정보</h3>
    <p className="match-muted">상대 업체의 업체 카드에 표시됩니다. 허가 종류·번호·유효기간을 바꾸면 운영자 확인이 다시 필요합니다.</p>
    {trust && <p><TrustBadge trust={trust} /> <TrustStats trust={trust} /></p>}
    <fieldset disabled={busy}>
      <div className="match-fields">
        <label>사업자등록번호<input maxLength={20} placeholder="000-00-00000" value={form.business_number} onChange={event => set({ business_number: event.target.value })} /></label>
        <label>사업장 주소<input maxLength={120} value={form.address} onChange={event => set({ address: event.target.value })} /></label>
        {role !== 'supplier' && <>
          <label>허가 종류<select value={form.permit_type} onChange={event => set({ permit_type: event.target.value })}>
            <option value="">선택 안 함</option>{types.map(type => <option key={type}>{type}</option>)}
          </select></label>
          <label>허가번호<input maxLength={60} value={form.permit_number} onChange={event => set({ permit_number: event.target.value })} /></label>
          <label>허가 유효기간<input type="date" value={form.permit_valid_until ?? ''} onChange={event => set({ permit_valid_until: event.target.value || null })} /></label>
        </>}
        {role === 'recycler' && <label>주 거래 방식<select value={form.price_model} onChange={event => set({ price_model: event.target.value })}>
          <option value="">선택 안 함</option><option value="매입">매입 (우리가 지급)</option><option value="처리비">처리비 (배출업체가 지급)</option><option value="협의">협의</option>
        </select></label>}
      </div>
      <button className="primary-button" type="submit">신뢰 정보 저장</button>
    </fieldset>
    {message && <p className="match-muted" role="status">{message}</p>}
  </form>
}

/** Operator page: check permit details companies entered. */
export function OperatorPermits() {
  const [items, setItems] = useState<OperatorCompany[] | null>(null)
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const rank = (item: OperatorCompany) => item.trust.permit_registered && !item.trust.permit_verified ? 0 : item.trust.permit_verified ? 1 : 2
  const load = () => api.operatorCompanies().then(result => setItems(result.sort((a, b) => rank(a) - rank(b))), failure => setError(errorText(failure)))
  useEffect(() => { void load() }, [])

  async function verify(id: string, verified: boolean) {
    setBusy(true)
    setError('')
    try { await api.verifyCompany(id, verified, notes[id] ?? ''); await load() } catch (failure) { setError(errorText(failure)) } finally { setBusy(false) }
  }

  const waiting = (items ?? []).filter(item => item.trust.permit_registered && !item.trust.permit_verified)
  return <section className="match-page">
    <header className="match-heading">
      <h1><BadgeCheck size={22} /> 허가 정보 확인</h1>
      <p>업체가 등록한 허가 정보를 허가증 사본이나 관할 기관 자료와 대조한 뒤 확인 처리하세요. 확인하면 업체 카드에 ‘허가 확인’ 배지가 붙습니다.</p>
    </header>
    <div className="deals-narrow">
      {error && <p className="match-error" role="alert">{error}</p>}
      {items && <p className="match-muted">확인 대기 {waiting.length}곳 · 전체 {items.length}곳</p>}
      {!items ? <p className="match-muted">불러오는 중입니다…</p> : items.map(item => <article key={item.id} className="match-card operator-row">
        <div className="match-card-head"><h2>{item.name} <small>{roleNames[item.role]}</small></h2><TrustBadge trust={item.trust} /></div>
        <dl className="deal-facts">
          <div><dt>허가 종류</dt><dd>{item.details.permit_type || '—'}</dd></div>
          <div><dt>허가번호</dt><dd>{item.details.permit_number || '—'}</dd></div>
          <div><dt>유효기간</dt><dd>{item.details.permit_valid_until || '—'}</dd></div>
          <div><dt>사업자등록번호</dt><dd>{item.details.business_number || '—'}</dd></div>
          <div><dt>주소</dt><dd>{item.details.address || '—'}</dd></div>
          {item.trust.verify_note && <div><dt>확인 메모</dt><dd>{item.trust.verify_note}</dd></div>}
        </dl>
        {item.trust.permit_registered && <div className="inline-form">
          <label>확인 메모<input maxLength={300} placeholder="예: 허가증 사본 대조 완료" value={notes[item.id] ?? ''} onChange={event => setNotes({ ...notes, [item.id]: event.target.value })} /></label>
          {item.trust.permit_verified
            ? <button type="button" className="subtle-button" disabled={busy} onClick={() => void verify(item.id, false)}>확인 취소</button>
            : <button type="button" className="primary-button" disabled={busy} onClick={() => void verify(item.id, true)}><BadgeCheck size={15} /> 확인 처리</button>}
        </div>}
      </article>)}
    </div>
  </section>
}
