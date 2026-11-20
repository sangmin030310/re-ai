import { useEffect, useState, type FormEvent } from 'react'
import { Megaphone, MessageSquare, Pencil, Plus, Send, X } from 'lucide-react'
import { api, materials, type DemandPost, type DemandPostInput, type Project } from './lib/api'
import { dateTime, errorText, km, priceSummary, tons, TrustBadge } from './ui'
import './deals.css'

function DemandCard({ demand, children }: { demand: DemandPost; children?: React.ReactNode }) {
  return <article className={`demand-card ${demand.status === 'closed' || demand.expired ? 'closed' : ''}`}>
    <div className="demand-card-head">
      <div>
        <strong>{demand.recycler_name}</strong>
        <small>{demand.city ?? ''}{km(demand.distance_km) ? ` · ${km(demand.distance_km)}` : ''}</small>
      </div>
      <TrustBadge trust={demand.trust} compact />
    </div>
    <p className="demand-title">{demand.material} 월 {tons(demand.monthly_ton)} 구합니다</p>
    <p className="match-muted">{priceSummary(demand.price_type, demand.unit_price)} · 수거·반입 지역 {demand.regions.join(', ')}
      {demand.until && <> · {demand.until}까지</>}</p>
    {demand.conditions && <p className="demand-conditions">{demand.conditions}</p>}
    {children}
  </article>
}

/** Supplier view: open demand posts that fit one saved request. */
export function DemandMatches({ projectId, onInquiry, title = '이 재질을 찾는 가공업체' }: {
  projectId: string
  onInquiry: (id: string) => void
  title?: string
}) {
  const [items, setItems] = useState<DemandPost[] | null>(null)
  const [target, setTarget] = useState<DemandPost | null>(null)
  const [content, setContent] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let ignore = false
    setItems(null)
    api.demands(projectId).then(result => { if (!ignore) setItems(result) }, failure => { if (!ignore) setError(errorText(failure)) })
    return () => { ignore = true }
  }, [projectId])

  async function reply(event: FormEvent) {
    event.preventDefault()
    if (!target || busy || !content.trim()) return
    setBusy(true)
    setError('')
    try {
      const { id } = await api.replyDemand(target.id, projectId, content.trim())
      onInquiry(id)
    } catch (failure) {
      setError(errorText(failure))
    } finally {
      setBusy(false)
    }
  }

  if (items && !items.length && !error) return null
  return <section className="match-card demand-matches" aria-label={title}>
    <div className="match-card-head"><h2><Megaphone size={16} /> {title}</h2>{items && <span>{items.length}건</span>}</div>
    {error && <p className="match-error" role="alert">{error}</p>}
    {!items ? <p className="match-muted">수요 공고를 찾는 중입니다…</p> : items.map(demand => <DemandCard demand={demand} key={demand.id}>
      {demand.my_inquiry_id ? <button type="button" className="subtle-button" onClick={() => onInquiry(demand.my_inquiry_id!)}><MessageSquare size={14} /> 대화 열기</button>
        : target?.id === demand.id ? <form className="match-form" onSubmit={reply}>
          <label>보낼 메시지<textarea rows={3} maxLength={2000} required value={content} onChange={event => setContent(event.target.value)} /></label>
          <div className="inbox-attachment">
            <button className="primary-button" type="submit" disabled={busy || !content.trim()}><Send size={14} /> 요청서와 함께 보내기</button>
            <button className="subtle-button" type="button" onClick={() => setTarget(null)}>취소</button>
          </div>
        </form>
        : <button type="button" className="subtle-button" onClick={() => {
          setTarget(demand)
          setContent(`안녕하세요. 공고를 보고 연락드립니다. 저희 요청서를 첨부합니다. ${demand.material} 공급 조건을 협의하고 싶습니다.`)
        }}><Send size={14} /> 이 공고에 답하기</button>}
    </DemandCard>)}
  </section>
}

/** Supplier page: pick one of my projects with a saved request, then browse matching posts. */
export function SupplierDemands({ projects, activeId, onInquiry }: {
  projects: Project[]
  activeId: string | null
  onInquiry: (id: string) => void
}) {
  const ready = projects.filter(project => project.profile && project.profile.material && project.profile.monthly_ton)
  const [projectId, setProjectId] = useState<string>(() => ready.find(project => project.id === activeId)?.id ?? ready[0]?.id ?? '')
  return <section className="match-page">
    <header className="match-heading">
      <h1>가공업체 수요 공고</h1>
      <p>가공업체가 “이런 재질을 구합니다”라고 올린 공고입니다. 내 요청서와 재질·지역이 맞는 공고만 보여드려요.</p>
    </header>
    <div className="deals-narrow">
      {ready.length ? <>
        <label className="match-form-label">답할 요청서<select value={projectId} onChange={event => setProjectId(event.target.value)}>
          {ready.map(project => <option key={project.id} value={project.id}>{project.title} · {String(project.profile.material)} 월 {String(project.profile.monthly_ton)}톤</option>)}
        </select></label>
        {projectId && <DemandMatches key={projectId} projectId={projectId} onInquiry={onInquiry} title="맞는 수요 공고" />}
        <p className="match-muted">맞는 공고가 없으면 이 영역이 비어 있습니다. 요청서의 재질과 배출 지역을 확인해 보세요.</p>
      </> : <div className="match-empty"><Megaphone size={24} /><p>먼저 <strong>요청서 · 업체 찾기</strong>에서 요청서를 저장하세요. 저장한 요청서로 공고에 답할 수 있습니다.</p></div>}
    </div>
  </section>
}

const emptyPost = (): DemandPostInput => ({
  material: 'PP', monthly_ton: 1, regions: [], price_type: '협의', unit_price: null, conditions: '', until: null,
})

/** Recycler page: my demand posts. */
export function RecyclerDemands({ onOpenInquiries }: { onOpenInquiries: () => void }) {
  const [items, setItems] = useState<DemandPost[] | null>(null)
  const [editing, setEditing] = useState<{ id: string | null; data: DemandPostInput; regions: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = () => api.myDemands().then(setItems, failure => setError(errorText(failure)))
  useEffect(() => { void load() }, [])

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!editing || busy) return
    const regions = editing.regions.split(/[,\s]+/).map(item => item.trim()).filter(Boolean)
    if (!regions.length) { setError('수거·반입 지역을 한 곳 이상 입력해 주세요.'); return }
    setBusy(true)
    setError('')
    try {
      const priced = editing.data.price_type === '매입' || editing.data.price_type === '처리비'
      const data = { ...editing.data, regions, unit_price: priced ? editing.data.unit_price : null }
      if (editing.id) await api.updateDemand(editing.id, data)
      else await api.createDemand(data)
      setEditing(null)
      await load()
    } catch (failure) {
      setError(errorText(failure))
    } finally {
      setBusy(false)
    }
  }

  async function close(id: string) {
    setBusy(true)
    try { await api.closeDemand(id); await load() } catch (failure) { setError(errorText(failure)) } finally { setBusy(false) }
  }

  const set = (patch: Partial<DemandPostInput>) => setEditing(previous => previous && { ...previous, data: { ...previous.data, ...patch } })

  return <section className="match-page">
    <header className="match-heading">
      <h1>우리 수요 공고</h1>
      <p>필요한 재질과 물량을 올리면 조건이 맞는 배출업체가 요청서를 붙여 연락합니다. 답장은 <button type="button" className="link-button" onClick={onOpenInquiries}>기업 문의함</button>에 도착합니다.</p>
    </header>
    <div className="deals-narrow">
      {error && <p className="match-error" role="alert">{error}</p>}
      {editing ? <form className="match-card match-form" onSubmit={save}>
        <div className="match-card-head"><h2>{editing.id ? '공고 수정' : '새 수요 공고'}</h2>
          <button type="button" className="subtle-button" onClick={() => setEditing(null)}><X size={14} /> 닫기</button></div>
        <fieldset disabled={busy}>
          <div className="match-fields">
            <label>재질<select value={editing.data.material} onChange={event => set({ material: event.target.value })}>
              {materials.filter(item => item !== '플라스틱(미상)').map(item => <option key={item}>{item}</option>)}
            </select></label>
            <label>월 필요량 (톤)<input type="number" min="0.001" step="any" required value={editing.data.monthly_ton}
              onChange={event => set({ monthly_ton: Number(event.target.value) })} /></label>
            <label>거래 방식<select value={editing.data.price_type} onChange={event => set({ price_type: event.target.value as DemandPostInput['price_type'] })}>
              <option value="협의">협의</option><option value="매입">매입 (우리가 지급)</option><option value="처리비">처리비 (배출업체가 지급)</option><option value="무상">무상</option>
            </select></label>
            <label>톤당 단가(원)<input type="number" min="0" step="1000" disabled={editing.data.price_type !== '매입' && editing.data.price_type !== '처리비'}
              value={editing.data.unit_price ?? ''} onChange={event => set({ unit_price: event.target.value ? Number(event.target.value) : null })} /></label>
          </div>
          <label>수거·반입 지역<input required placeholder="예: 전주, 완주, 익산" value={editing.regions}
            onChange={event => setEditing({ ...editing, regions: event.target.value })} /></label>
          <label><span className="field-title">반입 조건 <small>선택</small></span><textarea rows={3} maxLength={500} placeholder="예: 단일 재질, 이물질 5% 이하, 톤백 포장"
            value={editing.data.conditions} onChange={event => set({ conditions: event.target.value })} /></label>
          <label><span className="field-title">공고 마감일 <small>선택</small></span><input type="date" value={editing.data.until ?? ''}
            onChange={event => set({ until: event.target.value || null })} /></label>
          <button className="primary-button" type="submit">{editing.id ? '공고 수정' : '공고 올리기'}</button>
        </fieldset>
      </form> : <button type="button" className="primary-button deals-new" onClick={() => setEditing({ id: null, data: emptyPost(), regions: '' })}>
        <Plus size={16} /> 새 수요 공고</button>}
      {!items ? <p className="match-muted">공고를 불러오는 중입니다…</p>
        : !items.length ? <div className="match-empty"><Megaphone size={24} /><p>아직 올린 공고가 없습니다.</p></div>
        : items.map(demand => <DemandCard demand={demand} key={demand.id}>
          <div className="inbox-attachment">
            <span className="match-muted">{demand.status === 'closed' ? '마감됨' : demand.expired ? '마감일 지남' : '게시 중'} · 응답 {demand.response_count ?? 0}건 · {dateTime(demand.updated_at)} 수정</span>
            <button type="button" className="subtle-button" disabled={busy} onClick={() => setEditing({
              id: demand.id, regions: demand.regions.join(', '),
              data: { material: demand.material, monthly_ton: demand.monthly_ton, regions: demand.regions, price_type: demand.price_type,
                unit_price: demand.unit_price, conditions: demand.conditions, until: demand.until },
            })}><Pencil size={14} /> {demand.status === 'closed' ? '다시 게시' : '수정'}</button>
            {demand.status === 'open' && <button type="button" className="subtle-button" disabled={busy} onClick={() => void close(demand.id)}>마감</button>}
          </div>
        </DemandCard>)}
    </div>
  </section>
}
