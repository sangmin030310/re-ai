import { useEffect, useImperativeHandle, useRef, useState, type FormEvent, type Ref } from 'react'
import { ArrowDownToLine, ArrowLeft, ArrowRight, FileText, Handshake, Inbox, Paperclip, RefreshCw, Send, Upload } from 'lucide-react'
import {
  api, frequencies, legalStatuses, materials, newClientId, pricePreferences,
  type Company, type CompanyRole, type DocumentInfo, type IntakeRequest, type InquiryDetail, type InquiryReview,
  type InquiryReviewStatus, type InquirySummary, type Quote, type RequestAssessment, type ResponseRow,
} from './lib/api'
import './matching.css'
import './deals.css'
import CompanyMarket from './CompanyMarket'
import { DemandMatches } from './Demands'
import { dateTime, km, priceSummary, RequestReviewCard, TrustBadge } from './ui'

type Draft = {
  material: string; monthly_ton: string; region: string; contamination: string; packaging: string; notes: string
  legal_status: string; waste_code: string; frequency: string; address: string; price_preference: string
}
const extraDefaults = { legal_status: '확인 전', waste_code: '', frequency: '매월 정기', address: '', price_preference: '협의' }
function draftFrom(source: Partial<Record<keyof Draft, unknown>>): Draft {
  const text = (key: keyof Draft, fallback = '') => source[key] == null ? fallback : String(source[key])
  return {
    material: materials.includes(text('material')) ? text('material') : '',
    monthly_ton: text('monthly_ton'), region: text('region'), contamination: text('contamination'),
    packaging: text('packaging'), notes: text('notes'),
    legal_status: text('legal_status', extraDefaults.legal_status), waste_code: text('waste_code'),
    frequency: text('frequency', extraDefaults.frequency), address: text('address'),
    price_preference: text('price_preference', extraDefaults.price_preference),
  }
}
const sample: Draft = {
  material: 'PP', monthly_ton: '3', region: '전주', contamination: '육안상 기름·이물질 없음',
  packaging: '톤백 포장', notes: '자동차 부품 생산 과정에서 발생한 PP 스크랩입니다. 수거 가능 일정과 필요 자료를 알려주세요.',
  legal_status: '확인 전', waste_code: '', frequency: '매월 정기', address: '전주시 덕진구 산업단지로 00', price_preference: '매각 희망',
}
const getError = (error: unknown) => error instanceof Error ? error.message : '요청을 처리하지 못했습니다.'
const clock = (date: string) => new Date(date).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
const reviewLabels: Record<InquiryReviewStatus, string> = {
  accepted: '반입 가능',
  needs_info: '추가 확인 필요',
  declined: '반입 어려움',
}

export function canFindCompanies(profile: { material?: unknown; monthly_ton?: unknown; region?: unknown }) {
  const ton = Number(profile.monthly_ton)
  const material = typeof profile.material === 'string' ? profile.material : ''
  return materials.includes(material) && material !== '플라스틱(미상)'
    && ton >= 0.001 && ton <= 100000 && Boolean(typeof profile.region === 'string' && profile.region.trim())
}

function defaultInquiry(request: IntakeRequest, schedule = '수거 또는 반입 가능 일정') {
  const files = request.attachment_ids?.length ? ` 사진·자료 ${request.attachment_ids.length}건을 함께 보냅니다.` : ''
  return [
    `안녕하세요. ${request.region}에서 발생하는 ${request.material} 월 ${request.monthly_ton}톤(${request.frequency ?? '매월 정기'})의 반입 가능 여부를 문의드립니다.`,
    `${request.contamination && request.contamination !== '확인 필요' ? `요청서에 입력한 오염 상태는 ‘${request.contamination}’입니다.` : ''}${files} 반입 기준, ${schedule}, 톤당 가격(매입 또는 처리비)을 알려주시면 감사하겠습니다.`.trim(),
  ].join('\n\n')
}

function ResponsesTable({ rows, onInquiry, onOpenDeal, onRefresh, busy }: {
  rows: ResponseRow[]
  onInquiry: (id: string) => void
  onOpenDeal?: (id: string) => void
  onRefresh: () => void
  busy: boolean
}) {
  return <section className="match-card responses-card" aria-label="받은 답변 비교">
    <div className="match-card-head">
      <h2>받은 답변 비교 <small>{rows.length}곳</small></h2>
      <button type="button" className="subtle-button" onClick={onRefresh} disabled={busy}><RefreshCw size={14} /> 새로고침</button>
    </div>
    <div className="table-scroll"><table className="compare-table">
      <thead><tr><th>업체</th><th>허가</th><th>거리</th><th>검토 결과</th><th>가격</th><th>가능일</th><th>답장</th><th /></tr></thead>
      <tbody>{rows.map(row => <tr key={row.inquiry_id}>
        <td><strong>{row.company_name}</strong><small>{row.city}</small></td>
        <td><TrustBadge trust={row.trust} compact /></td>
        <td>{km(row.distance_km) ?? '—'}</td>
        <td>{row.review ? <span className={`inbox-review-status ${row.review.status}`} title={row.review.reason}>{reviewLabels[row.review.status]}</span>
          : <span className="inbox-review-status pending">검토 대기</span>}</td>
        <td>{row.quote ? priceSummary(row.quote.price_type, row.quote.unit_price) : '—'}</td>
        <td>{row.quote?.available_from ?? '—'}</td>
        <td>{row.replied_at ? dateTime(row.replied_at) : '아직 없음'}</td>
        <td className="compare-actions">
          {row.deal_id && onOpenDeal ? <button type="button" className="primary-button" onClick={() => onOpenDeal(row.deal_id!)}><Handshake size={14} /> 거래 건</button>
            : <button type="button" className="subtle-button" onClick={() => onInquiry(row.inquiry_id)}>대화 열기</button>}
        </td>
      </tr>)}</tbody>
    </table></div>
    <p className="match-muted">가격과 가능일은 가공업체가 검토 결과에 남긴 값입니다. 조건이 맞는 업체와 대화에서 <strong>거래 건 만들기</strong>를 누르면 단가·물량·운송 담당을 확정할 수 있습니다.</p>
  </section>
}

function DocumentPreview({ request }: { request: Partial<IntakeRequest> }) {
  const fields = [
    ['재질', request.material === '플라스틱(미상)' ? '' : request.material], ['월간 발생량', request.monthly_ton ? `${request.monthly_ton}톤` : ''],
    ['배출 지역', request.region], ['오염 상태', request.contamination], ['포장 상태', request.packaging],
    ['발생 주기', request.frequency], ['거래 희망', request.price_preference],
    ['법적 지위', request.legal_status && request.legal_status !== '확인 전' ? `${request.legal_status} (배출업체 입력)` : request.legal_status],
    ...(request.waste_code ? [['폐기물 분류번호', request.waste_code]] : []),
    ...(request.address ? [['상차 주소', request.address]] : []),
    ...(request.attachment_ids?.length ? [['첨부 자료', `${request.attachment_ids.length}건`]] : []),
  ].filter(([, value]) => value !== undefined)
  return <div className="match-document">
    <div className="match-document-title"><FileText size={19} /><h3>폐기물 인수 검토 요청서</h3></div>
    <dl>{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || <span className="draft-missing">미입력</span>}</dd></div>)}</dl>
    {request.notes && <p>{request.notes}</p>}
  </div>
}

export interface RequestDraftEditor {
  projectId: string | null
  currentDraft: () => IntakeRequest | undefined
  recordSaved: (request: IntakeRequest) => void
}

export function Matching({
  projectId, profile, onCreate, onInquiry, onSaved, embedded = false,
  initialCompanies, onBrowse, onBackToChat, chatBusy = false, canPublish = false, draftEditor, onOpenDeal,
}: {
  onOpenDeal?: (id: string) => void
  embedded?: boolean
  projectId: string | null
  profile: Partial<IntakeRequest>
  onCreate: () => Promise<string | undefined>
  onInquiry: (id: string) => void
  onSaved?: (request: IntakeRequest) => void
  initialCompanies?: Company[]
  onBrowse?: (companies: Company[]) => void
  onBackToChat?: () => void
  chatBusy?: boolean
  canPublish?: boolean
  draftEditor?: Ref<RequestDraftEditor>
}) {
  const chatDraft = draftFrom(profile)
  const [draft, setDraft] = useState(chatDraft)
  const [attachments, setAttachments] = useState<string[]>(() => Array.isArray(profile.attachment_ids) ? profile.attachment_ids : [])
  const [projectFiles, setProjectFiles] = useState<DocumentInfo[]>([])
  const [review, setReview] = useState<RequestAssessment | null>(null)
  const [reviewState, setReviewState] = useState({ loading: false, error: '' })
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [batchContent, setBatchContent] = useState('')
  const [batchNotice, setBatchNotice] = useState('')
  const [responses, setResponses] = useState<ResponseRow[] | null>(null)
  const lastChat = useRef(chatDraft)
  const editedFields = useRef(new Set<keyof Draft>())
  const [previewOpen, setPreviewOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [saved, setSaved] = useState<IntakeRequest | null>(null)
  const [listing, setListing] = useState<IntakeRequest | null>(null)
  const [available, setAvailable] = useState('')
  const [companies, setCompanies] = useState<Company[]>(initialCompanies ?? [])
  const [marketOpen, setMarketOpen] = useState(Boolean(initialCompanies))
  const [selected, setSelected] = useState<string | null>(null)
  const [contacts, setContacts] = useState<Record<string, string>>({})
  const [target, setTarget] = useState<Company | null>(null)
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(Boolean(projectId))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!previewOpen || loading) return
    document.getElementById('match-request-preview')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [previewOpen, loading])

  useEffect(() => {
    if (!projectId) return
    const id = projectId
    let ignore = false
    async function load() {
      try {
        const result = await api.intakeRequest(id)
        if (ignore) return
        setContacts(result.inquiries)
        setSelected(result.selected_company_id)
        setListing(result.listing)
        setAvailable(result.listing ? String(result.listing.monthly_ton) : '')
        if (result.request) {
          setSaved(result.request)
          setAttachments(result.request.attachment_ids ?? [])
          const request = draftFrom(result.request)
          setDraft(previous => {
            if (!embedded) return request
            const merged = { ...request }
            for (const key of Object.keys(request) as (keyof Draft)[]) {
              if (previous[key] && previous[key] !== extraDefaults[key as keyof typeof extraDefaults]) merged[key] = previous[key]
            }
            return merged
          })
        }
      } catch (failure) {
        if (!ignore) setError(getError(failure))
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    void load()
    return () => { ignore = true }
  }, [projectId, embedded])

  useEffect(() => {
    const previous = lastChat.current
    lastChat.current = draftFrom(profile)
    const next = lastChat.current
    if (!embedded || marketOpen) return
    const promoted = (Object.keys(next) as (keyof typeof next)[]).filter(key => (
      next[key] && next[key] !== previous[key] && !editedFields.current.has(key)
    ))
    if (promoted.length) {
      setDraft(draft => {
        const merged = { ...draft }
        for (const key of promoted) merged[key] = next[key]
        return merged
      })
    }
  }, [embedded, marketOpen, profile.material, profile.monthly_ton, profile.region, profile.contamination, profile.packaging, profile.notes])

  const change = (key: keyof Draft, value: string) => {
    editedFields.current.add(key)
    setDraft(previous => ({ ...previous, [key]: value }))
    setTarget(null)
  }

  const current = { ...draft, monthly_ton: Number(draft.monthly_ton) }
  const requestToSave: IntakeRequest = {
    material: current.material,
    monthly_ton: current.monthly_ton,
    region: current.region.trim(),
    contamination: current.contamination.trim() || '확인 필요',
    packaging: current.packaging.trim() || '확인 필요',
    notes: current.notes.trim(),
    legal_status: (current.legal_status || '확인 전') as IntakeRequest['legal_status'],
    waste_code: current.waste_code.trim(),
    frequency: (current.frequency || '매월 정기') as IntakeRequest['frequency'],
    address: current.address.trim(),
    price_preference: (current.price_preference || '협의') as IntakeRequest['price_preference'],
    attachment_ids: attachments,
  }
  const complete = canFindCompanies(current)
  const same = (left: unknown, right: unknown) => JSON.stringify(left ?? null) === JSON.stringify(right ?? null)
  const normalizedSaved = saved ? { ...saved, ...Object.fromEntries(Object.entries(extraDefaults).map(([key, value]) => [key, saved[key as keyof IntakeRequest] ?? value])), attachment_ids: saved.attachment_ids ?? [] } : null
  const dirty = !normalizedSaved || (Object.keys(requestToSave) as (keyof IntakeRequest)[]).some(key => !same(requestToSave[key], normalizedSaved[key]))

  function recordSaved(request: IntakeRequest) {
    const changes = Object.entries(request).filter(([key, value]) => !same(saved?.[key as keyof IntakeRequest], value))
    if (saved && changes.some(([key]) => key !== 'notes' && key !== 'attachment_ids')) {
      setListing(null)
      setAvailable('')
    }
    if (changes.length) setSelected(null)
    setSaved(request)
    setDraft(draftFrom(request))
    setAttachments(request.attachment_ids ?? [])
    editedFields.current.clear()
    setEditing(false)
  }

  useEffect(() => {
    if (!projectId) return
    let ignore = false
    api.documents(projectId).then(files => { if (!ignore) setProjectFiles(files.filter(file => file.source !== 'request')) }).catch(() => {})
    return () => { ignore = true }
  }, [projectId])

  const reviewKey = saved && !dirty ? JSON.stringify(saved) : ''
  useEffect(() => {
    if (!projectId || !reviewKey) return
    let ignore = false
    setReviewState({ loading: true, error: '' })
    api.requestReview(projectId).then(
      result => { if (!ignore) { setReview(result); setReviewState({ loading: false, error: '' }) } },
      failure => { if (!ignore) setReviewState({ loading: false, error: getError(failure) }) },
    )
    return () => { ignore = true }
  }, [projectId, reviewKey])

  async function loadResponses() {
    if (!projectId) return
    try { setResponses(await api.responses(projectId)) } catch (failure) { setError(getError(failure)) }
  }
  const contactCount = Object.keys(contacts).length
  useEffect(() => {
    if (!marketOpen || !projectId || !contactCount) return
    void loadResponses()
    const timer = window.setInterval(() => void loadResponses(), 10000)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [marketOpen, projectId, contactCount])

  async function uploadAttachment(file: File) {
    if (!projectId) return
    setBusy(true)
    setError('')
    try {
      const uploaded = await api.upload(projectId, file)
      setProjectFiles(previous => [uploaded, ...previous])
      setAttachments(previous => previous.length < 10 ? [...previous, uploaded.id] : previous)
    } catch (failure) {
      setError(getError(failure))
    } finally {
      setBusy(false)
    }
  }

  function togglePick(company: Company) {
    setPicked(previous => {
      const next = new Set(previous)
      if (next.has(company.id)) next.delete(company.id)
      else if (next.size < 10) next.add(company.id)
      return next
    })
    if (!batchContent && saved) setBatchContent(defaultInquiry(saved))
  }

  async function sendBatch(event: FormEvent) {
    event.preventDefault()
    if (!projectId || !saved || !picked.size || busy || !batchContent.trim()) return
    setBusy(true)
    setError('')
    try {
      const result = await api.sendBatch(projectId, [...picked], batchContent.trim(), saved)
      setContacts(previous => ({
        ...previous,
        ...Object.fromEntries([...result.created, ...result.skipped.filter(item => item.id)].map(item => [item.recipient_id, item.id!])),
      }))
      setPicked(new Set())
      setBatchNotice(`${result.created.length}곳에 문의를 보냈습니다.${result.skipped.length ? ` ${result.skipped.length}곳은 건너뛰었습니다(${result.skipped.map(item => item.reason).join(' ')}).` : ''}`)
      await loadResponses()
    } catch (failure) {
      setError(getError(failure))
    } finally {
      setBusy(false)
    }
  }

  useImperativeHandle(draftEditor, () => ({
    projectId,
    currentDraft: () => loading ? undefined : requestToSave,
    recordSaved,
  }))

  async function saveAndContinue(findCompanies: boolean) {
    if (busy || chatBusy || loading || !projectId || !complete) return
    setError('')
    setBusy(true)
    try {
      if (dirty || !findCompanies) {
        const request = await api.saveIntake(projectId, requestToSave)
        recordSaved(request)
        onSaved?.(request)
      }
      setEditing(false)
      if (findCompanies) {
        const candidates = await api.companies(projectId)
        if (onBrowse) onBrowse(candidates)
        else {
          setCompanies(candidates)
          setMarketOpen(true)
        }
      }
    } catch (failure) {
      setError(getError(failure))
    } finally {
      setBusy(false)
    }
  }

  function save(event: FormEvent) {
    event.preventDefault()
    void saveAndContinue(false)
  }

  async function publish(remove: boolean) {
    if (!projectId || !saved || dirty || busy || chatBusy) return
    setBusy(true)
    setError('')
    try {
      if (remove) {
        await api.unpublishSupply(projectId)
        setListing(null)
        setAvailable('')
      } else {
        const result = await api.publishSupply(projectId, Number(available))
        setListing(result)
        setAvailable(String(result.monthly_ton))
      }
    } catch (failure) {
      setError(getError(failure))
    } finally {
      setBusy(false)
    }
  }

  const publication = canPublish && saved && !dirty && <section className="match-card supply-publication">
    <div className="match-card-head"><h2>남은 물량 공개</h2>{listing && <span>공개 중 · {listing.monthly_ton}톤</span>}</div>
    <p>업체 이름, 재질, 배출 지역, 오염·포장 상태, 남은 물량이 Re AI 가공업체에 표시됩니다.</p>
    <form className="match-form" onSubmit={event => { event.preventDefault(); void publish(false) }}>
      <label>공개할 남은 물량 (톤)<input type="number" required step="any" min="0.001" max={saved.monthly_ton} placeholder={String(saved.monthly_ton)} value={available} onChange={event => setAvailable(event.target.value)} /></label>
      <div className="inbox-attachment">
        <button className="primary-button" type="submit" disabled={busy || chatBusy}>{listing ? '공개 물량 수정' : '가공업체에 공개'}</button>
        {listing && <button className="subtle-button" type="button" disabled={busy} onClick={() => void publish(true)}>공개 종료</button>}
      </div>
    </form>
  </section>

  async function contact(company: Company) {
    if (!projectId || !saved || busy) return
    if (contacts[company.id]) {
      onInquiry(contacts[company.id])
      return
    }
    setBusy(true)
    setError('')
    try {
      if (selected !== company.id) {
        const result = await api.selectCompany(projectId, company.id, saved)
        setSelected(result.selected_company_id)
      }
      setContent(defaultInquiry(saved, company.transport === '업체 수거' ? '수거 가능 일정' : '직접 반입 가능 일정'))
      setTarget(company)
      requestAnimationFrame(() => document.getElementById('match-compose')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
    } catch (failure) {
      setError(getError(failure))
    } finally {
      setBusy(false)
    }
  }

  async function send(event: FormEvent) {
    event.preventDefault()
    if (!target || target.id !== selected || !projectId || !saved || busy || !content.trim()) return
    setBusy(true)
    setError('')
    try {
      const result = await api.sendInquiry(projectId, target.id, content, saved)
      onInquiry(result.id)
    } catch (failure) {
      setError(getError(failure))
    } finally {
      setBusy(false)
    }
  }

  return <section className={embedded ? "match-page chat-intake-card" : "match-page"}>
    {embedded ? <div className="chat-intake-summary">
      <div>
        <h2>{complete ? '조건에 맞는 업체를 찾아보세요' : '폐기물 요청서 작성 중'}</h2>
        <p>{complete ? `${current.material} · 월 ${current.monthly_ton}톤 · ${current.region}` : '재질, 월간 발생량, 배출 지역을 알려주세요.'}</p>
      </div>
      <div className="chat-intake-actions">
        <button className="subtle-button" type="button" aria-expanded={previewOpen} onClick={() => setPreviewOpen(!previewOpen)}>
          {previewOpen ? '요청서 초안 접기' : '요청서 초안 보기'}
        </button>
        {complete && <button className="primary-button" type="button" disabled={loading || busy || chatBusy} onClick={() => void saveAndContinue(true)}>
          {busy ? '업체를 찾는 중…' : '추천 업체 보기'} <ArrowRight size={16} />
        </button>}
      </div>
    </div> : <header className="match-heading">
      {marketOpen && <button className="subtle-button market-back" disabled={busy} onClick={() => {
        if (onBackToChat) onBackToChat()
        else { setMarketOpen(false); setTarget(null) }
      }}><ArrowLeft size={16} /> {onBackToChat ? '채팅으로 돌아가기' : '요청서로 돌아가기'}</button>}
      <h1>{marketOpen ? '내 폐기물을 보낼 업체 찾기' : '폐기물 요청서 작성'}</h1>
      <p>{marketOpen ? '이동 목적지와 운반 조건을 비교하고, 원하는 업체를 직접 선택하세요.' : '배출 정보를 확인하고 업체를 찾는 데 사용할 요청서를 저장하세요.'}</p>
    </header>}
    {error && <p className="match-error" role="alert">{error}</p>}
    {embedded && !previewOpen ? null : !projectId ? <div className="match-empty">
      <FileText size={24} />
      <h2>요청서를 저장할 프로젝트가 필요합니다</h2>
      <button className="primary-button" disabled={busy} onClick={async () => {
        setBusy(true)
        const id = await onCreate()
        if (!id) setError('프로젝트를 만들지 못했습니다.')
        setBusy(false)
      }}>새 프로젝트 만들기 <ArrowRight size={16} /></button>
    </div> : loading ? <p className="match-loading">요청서를 불러오는 중입니다…</p> :
    marketOpen && saved ? <div className="market-layout">
      <aside className="supply-summary market-summary">
        <div className="match-card"><DocumentPreview request={saved} /></div>
        <RequestReviewCard review={review} loading={reviewState.loading} error={reviewState.error} />
        {canPublish && projectId && <DemandMatches projectId={projectId} onInquiry={onInquiry} />}
        {publication}
      </aside>
      <div className="market-main">
        {batchNotice && <p className="match-notice" role="status">{batchNotice}</p>}
        {responses && responses.length > 0 && <ResponsesTable rows={responses} onInquiry={onInquiry} onOpenDeal={onOpenDeal}
          onRefresh={() => void loadResponses()} busy={busy} />}
        {picked.size > 0 && <form className="match-card batch-compose" onSubmit={sendBatch}>
          <div className="match-card-head"><h2>선택한 {picked.size}곳에 한 번에 문의</h2>
            <button type="button" className="subtle-button" onClick={() => setPicked(new Set())} disabled={busy}>선택 해제</button></div>
          <p className="match-attachment"><FileText size={16} /> 요청서{saved.attachment_ids?.length ? `와 첨부 자료 ${saved.attachment_ids.length}건이` : '가'} 함께 전달됩니다. 각 업체와는 따로 대화합니다.</p>
          <label className="match-form-label">문의 메시지<textarea rows={4} required maxLength={2000} disabled={busy} value={batchContent} onChange={event => setBatchContent(event.target.value)} /></label>
          <button className="primary-button" type="submit" disabled={busy || !batchContent.trim()}><Send size={16} /> {picked.size}곳에 견적 요청 보내기</button>
        </form>}
        <CompanyMarket companies={companies} request={saved} selected={selected} busy={busy} onContact={company => void contact(company)} hasContact={id => Boolean(contacts[id])} onNavigate={() => setTarget(null)}
          picked={picked} onTogglePick={togglePick} />
        {target && target.id === selected && <section id="match-compose" className="match-card">
          <div className="match-card-head"><h2>{target.name}에 문의</h2><button className="subtle-button" onClick={() => setTarget(null)} disabled={busy}>닫기</button></div>
          <form className="match-form" onSubmit={send}>
            <p className="match-attachment"><FileText size={16} /> 폐기물 인수 검토 요청서.docx 첨부됨</p>
            <label>문의 메시지<textarea rows={3} required maxLength={2000} disabled={busy} value={content} onChange={e => setContent(e.target.value)} /></label>
            {error && <p className="match-error" role="alert">{error}</p>}
            <button className="primary-button" type="submit" disabled={busy || !content.trim()}><Send size={16} /> 문의 전송</button>
          </form>
        </section>}
      </div>
    </div> : <div className={embedded && !editing ? "match-grid request-preview-only" : "match-grid"}>
      {(!embedded || editing) && <section className="match-card">
        <div className="match-card-head">
          <h2>배출 정보</h2>
          {embedded ? <button type="button" className="subtle-button" onClick={() => setEditing(false)}>양식 접기</button> :
            <button type="button" className="subtle-button" disabled={busy} onClick={() => {
              for (const key of Object.keys(sample) as (keyof typeof sample)[]) editedFields.current.add(key)
              setDraft(sample)
              setTarget(null)
            }}>예시 정보 채우기</button>}
        </div>
        {embedded && <p className="draft-hint">항목이 헷갈리면 아래 채팅에 “이건 잘 모르겠어요”라고 물어보세요.</p>}
        <form className="match-form" onSubmit={save}>
          <fieldset disabled={busy}>
          <div className="match-fields">
            <label>재질<select required value={draft.material} onChange={e => change('material', e.target.value)}>
              <option value="">재질 선택</option>
              {materials.map(material => <option key={material}>{material}</option>)}
            </select></label>
            <label>월간 발생량 (톤)<input type="number" min="0.001" max="100000" step="any" required value={draft.monthly_ton} onChange={e => change('monthly_ton', e.target.value)} /></label>
            <label>배출 지역<input required maxLength={50} placeholder="예: 전주" value={draft.region} onChange={e => change('region', e.target.value)} /></label>
            <label><span className="field-title">포장 상태 <small>선택</small></span><input maxLength={100} placeholder="예: 톤백 포장" value={draft.packaging} onChange={e => change('packaging', e.target.value)} /></label>
          </div>
          <label><span className="field-title">오염 상태 <small>선택</small></span><input maxLength={100} placeholder="예: 기름·이물질 없음" value={draft.contamination} onChange={e => change('contamination', e.target.value)} /></label>
          <label><span className="field-title">추가 전달 사항 <small>선택</small></span><textarea rows={3} maxLength={500} value={draft.notes} onChange={e => change('notes', e.target.value)} /></label>
          <details className="match-extra" open={Boolean(draft.address || draft.waste_code || attachments.length)}>
            <summary>거래·확인 정보 <small>선택 · 업체가 견적을 내는 데 도움이 됩니다</small></summary>
            <div className="match-fields">
              <label>발생 주기<select value={draft.frequency} onChange={e => change('frequency', e.target.value)}>
                {frequencies.map(item => <option key={item}>{item}</option>)}
              </select></label>
              <label>거래 희망<select value={draft.price_preference} onChange={e => change('price_preference', e.target.value)}>
                {pricePreferences.map(item => <option key={item}>{item}</option>)}
              </select></label>
              <label><span className="field-title">법적 지위 <small>아는 경우</small></span><select value={draft.legal_status} onChange={e => change('legal_status', e.target.value)}>
                {legalStatuses.map(item => <option key={item}>{item}</option>)}
              </select></label>
              <label><span className="field-title">폐기물 분류번호 <small>선택</small></span><input maxLength={30} placeholder="예: 51-03-01" value={draft.waste_code} onChange={e => change('waste_code', e.target.value)} /></label>
            </div>
            <label><span className="field-title">상차 주소 <small>공개 물량에는 표시되지 않음</small></span><input maxLength={120} placeholder="예: 전주시 덕진구 ○○로 12" value={draft.address} onChange={e => change('address', e.target.value)} /></label>
            <div className="match-attachments">
              <span className="field-title"><Paperclip size={14} /> 사진·성상분석표 첨부 <small>{attachments.length}/10</small></span>
              {projectFiles.length > 0 && <ul>{projectFiles.map(file => <li key={file.id}><label>
                <input type="checkbox" checked={attachments.includes(file.id)} onChange={() => setAttachments(previous => previous.includes(file.id)
                  ? previous.filter(id => id !== file.id) : previous.length < 10 ? [...previous, file.id] : previous)} />
                {file.name}
              </label></li>)}</ul>}
              <label className="subtle-button upload-button"><Upload size={14} /> 파일 올려서 첨부
                <input type="file" hidden accept=".pdf,.png,.jpg,.jpeg,.docx,.xlsx,.txt,.csv,.hwp,.hwpx"
                  onChange={event => { const file = event.target.files?.[0]; if (file) void uploadAttachment(file); event.target.value = '' }} />
              </label>
            </div>
          </details>
          <button className="primary-button" disabled={busy || chatBusy || !complete} type="submit">요청서 저장 <ArrowRight size={16} /></button>
          </fieldset>
        </form>
      </section>}

      <section className="match-card" id="match-request-preview">
        <div className="match-card-head">
          <h2>{saved && !dirty ? '저장한 요청서' : '요청서 초안'}</h2>
          {embedded && !editing && <button className="subtle-button" disabled={busy} onClick={() => setEditing(true)}>직접 수정</button>}
          {saved && !dirty && <button className="subtle-button" onClick={() => void api.downloadIntake(projectId).catch(failure => setError(getError(failure)))}><ArrowDownToLine size={16} /> Word 다운로드</button>}
        </div>
        {embedded && dirty ? <>
          <DocumentPreview request={requestToSave} />
          {!complete && <p className="draft-hint">비어 있는 항목은 채팅으로 답하거나 직접 수정에서 입력할 수 있습니다.</p>}
          {!editing && <button className="primary-button market-browse" disabled={busy || chatBusy || !complete} onClick={() => void saveAndContinue(false)}>요청서 저장 <ArrowRight size={16} /></button>}
        </> : saved && !dirty ? <>
          <DocumentPreview request={saved} />
          {!embedded && <RequestReviewCard review={review} loading={reviewState.loading} error={reviewState.error} />}
          {!embedded && <button className="primary-button market-browse" disabled={busy || chatBusy} onClick={() => void saveAndContinue(true)}>이 요청서로 업체 찾기 <ArrowRight size={16} /></button>}
        </> : <div className="match-empty small">
          <FileText size={24} />
          <p>{saved ? '변경한 배출 정보를 저장하면 문서에 반영됩니다.' : '배출 정보를 저장하면 발송할 문서를 확인할 수 있습니다.'}</p>
        </div>}
      </section>

      {publication}
    </div>}
  </section>
}

function InquiryReviewPanel({ inquiry, canEdit, onSaved }: {
  inquiry: InquiryDetail
  canEdit: boolean
  onSaved: (review: InquiryReview) => void
}) {
  const [editing, setEditing] = useState(false)
  const [status, setStatus] = useState<InquiryReviewStatus | ''>('')
  const [reason, setReason] = useState('')
  const [quote, setQuote] = useState<{ price_type: string; unit_price: string; available_from: string }>({ price_type: '', unit_price: '', available_from: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const review = inquiry.review

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!status || !reason.trim() || busy) return
    setBusy(true)
    setError('')
    try {
      const priced = quote.price_type === '매입' || quote.price_type === '처리비'
      const body: Partial<Quote> = {
        price_type: (quote.price_type || null) as Quote['price_type'],
        unit_price: priced && quote.unit_price ? Number(quote.unit_price) : null,
        available_from: quote.available_from || null,
      }
      onSaved(await api.saveQuoteReview(inquiry.id, status, reason, body))
      setEditing(false)
    } catch (failure) {
      setError(getError(failure))
    } finally {
      setBusy(false)
    }
  }

  return <section className="inbox-review" aria-label="가공업체 검토 결과">
    <div className="inbox-review-heading">
      <h3>가공업체 검토 결과</h3>
      <strong className={`inbox-review-status ${review?.status ?? 'pending'}`} role="status">
        {review ? reviewLabels[review.status] : '검토 대기'}
      </strong>
    </div>
    {review && <p className="inbox-review-reason">{review.reason}</p>}
    {review?.quote && <p className="inbox-review-quote">
      <strong>견적</strong> {priceSummary(review.quote.price_type, review.quote.unit_price)}
      {review.quote.available_from && <> · {review.quote.available_from}부터 가능</>}
    </p>}
    {canEdit && (editing ? <form className="match-form" onSubmit={save}>
      <fieldset disabled={busy}>
        <label>결과 선택<select required value={status} onChange={event => setStatus(event.target.value as InquiryReviewStatus | '')}>
          <option value="" disabled>검토 결과를 선택하세요</option>
          {Object.entries(reviewLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
        </select></label>
        <label>검토 사유<textarea value={reason} onChange={event => setReason(event.target.value)} rows={2} required maxLength={300}
          placeholder="예: 필름 혼입 여부를 확인할 수 있도록 샘플 사진을 보내주세요." /></label>
        <div className="match-fields">
          <label><span className="field-title">거래 방식 <small>선택</small></span><select value={quote.price_type} onChange={event => setQuote({ ...quote, price_type: event.target.value })}>
            <option value="">입력 안 함</option>
            <option value="매입">매입 (우리가 지급)</option>
            <option value="처리비">처리비 (배출업체가 지급)</option>
            <option value="무상">무상</option>
            <option value="협의">협의</option>
          </select></label>
          <label><span className="field-title">톤당 단가(원) <small>선택</small></span><input type="number" min="0" step="1000" disabled={quote.price_type !== '매입' && quote.price_type !== '처리비'}
            value={quote.unit_price} onChange={event => setQuote({ ...quote, unit_price: event.target.value })} /></label>
        </div>
        <label><span className="field-title">반입 가능 시작일 <small>선택</small></span><input type="date" value={quote.available_from} onChange={event => setQuote({ ...quote, available_from: event.target.value })} /></label>
        <div className="inbox-review-actions">
          <button className="primary-button" type="submit" disabled={!status || !reason.trim()}>{busy ? '저장 중…' : '검토 결과 저장'}</button>
          <button className="subtle-button" type="button" onClick={() => { setEditing(false); setError('') }}>취소</button>
        </div>
      </fieldset>
      {error && <p className="match-error" role="alert">{error}</p>}
    </form> : <button className="subtle-button" type="button" onClick={() => {
      setStatus(review?.status ?? '')
      setReason(review?.reason ?? '')
      setQuote({
        price_type: review?.quote?.price_type ?? '', unit_price: review?.quote?.unit_price?.toString() ?? '',
        available_from: review?.quote?.available_from ?? '',
      })
      setEditing(true)
    }}>{review ? '검토 결과·견적 수정' : '검토 결과·견적 남기기'}</button>)}
  </section>
}

export function Inquiries({
  workspace, role, selectedId, onSelect, onBackToWorkspace, onOpenDeal,
}: {
  workspace: string
  role: CompanyRole
  selectedId: string | null
  onSelect: (id: string | null) => void
  onBackToWorkspace?: () => void
  onOpenDeal?: (id: string) => void
}) {
  const [items, setItems] = useState<InquirySummary[]>([])
  const [thread, setThread] = useState<InquiryDetail | null>(null)
  const [preview, setPreview] = useState(false)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [syncError, setSyncError] = useState('')
  const [error, setError] = useState('')
  const retry = useRef<{ content: string; id: string } | null>(null)
  const contentBox = useRef<HTMLDivElement>(null)
  const currentThread = thread?.id === selectedId ? thread : null
  const latest = currentThread?.messages.at(-1)?.sequence

  useEffect(() => {
    let ignore = false
    let inFlight = false
    async function refresh() {
      if (inFlight) return
      inFlight = true
      try {
        const [inbox, detail] = await Promise.all([
          api.inquiries(), selectedId ? api.inquiry(selectedId) : Promise.resolve(null),
        ])
        if (ignore) return
        setItems(inbox)
        setThread(detail)
        setSyncError('')
      } catch (failure) {
        if (!ignore) setSyncError(getError(failure))
      } finally {
        inFlight = false
        if (!ignore) setLoading(false)
      }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 1500)
    return () => { ignore = true; window.clearInterval(timer) }
  }, [selectedId])

  useEffect(() => {
    const box = contentBox.current
    if (box) box.scrollTop = box.scrollHeight
  }, [latest])

  async function send(event: FormEvent) {
    event.preventDefault()
    const content = draft.trim()
    if (!selectedId || !content || busy) return
    setBusy(true)
    setError('')
    if (retry.current?.content !== content) retry.current = { content, id: newClientId() }
    try {
      await api.reply(selectedId, content, retry.current.id)
      retry.current = null
      setDraft('')
    } catch (failure) {
      setError(getError(failure))
    } finally {
      setBusy(false)
    }
  }

  async function startDeal(inquiry: InquiryDetail) {
    setBusy(true)
    setError('')
    try {
      const deal = await api.createDeal(inquiry.id)
      onOpenDeal?.(deal.id)
    } catch (failure) {
      setError(getError(failure))
    } finally {
      setBusy(false)
    }
  }

  const otherCompany = (item: InquirySummary | InquiryDetail) => workspace === item.sender_id ? item.recipient_name : item.sender_name
  const dealParticipant = role === 'supplier' || role === 'recycler'

  return <section className="match-page inbox-page">
    <header className="match-heading">
      {onBackToWorkspace && <button className="subtle-button market-back" onClick={onBackToWorkspace}>
        <ArrowLeft size={16} /> {role === 'recycler' ? '공급처 찾기로 돌아가기' : 'AI 대화로 돌아가기'}
      </button>}
      <h1>{onBackToWorkspace ? '업체 대화' : '기업 문의함'}</h1>
      <p>{role === 'carrier' ? '이전 방식으로 받은 운송 문의입니다. 새 운송 요청은 거래 건 화면에서 확인하세요.' : '보낸 문의와 받은 문의를 확인하고, 조건이 맞으면 거래 건을 만들어 진행하세요.'}</p>
    </header>
    {syncError && <p className="match-error" role="alert">{syncError}</p>}
    <div className="inbox-grid">
      <section className="match-card thread-list">
        <h2>문의 목록 <small>{items.length}</small></h2>
        {items.length === 0 && <p className="match-muted">{loading ? '문의함을 불러오는 중입니다…' : '아직 문의가 없습니다.'}</p>}
        {items.map(item => <button key={item.id} disabled={busy} className={selectedId === item.id ? 'chosen-thread' : ''} onClick={() => {
          if (selectedId === item.id) return
          setPreview(false)
          setDraft('')
          setError('')
          retry.current = null
          onSelect(item.id)
        }}>
          <strong>{otherCompany(item)}</strong>
          <span>{item.initiated_by === workspace ? '보낸 문의' : '받은 문의'} · {item.recipient_role === 'carrier' ? '운송' : item.demand_id ? '수요 공고 응답' : '가공'} · {item.material} · {item.last_message}</span>
          <span className="thread-badges">
            {item.recipient_role === 'recycler' && <small className={`inbox-review-status ${item.review?.status ?? 'pending'}`}>
              {item.review ? reviewLabels[item.review.status] : '검토 대기'}
            </small>}
            {item.deal_id && <small className="inbox-review-status deal">거래 진행 중</small>}
          </span>
        </button>)}
      </section>
      <section className="match-card inbox-thread">
        {currentThread ? <>
          <div className="match-card-head"><h2>{otherCompany(currentThread)}</h2><span>{currentThread.request.material} · 월 {currentThread.request.monthly_ton}톤</span></div>
          {currentThread.recipient_role === 'recycler' && workspace !== currentThread.recipient_id && <p className="match-muted"><TrustBadge trust={currentThread.recipient_trust} /></p>}
          {currentThread.transport_to && <p className="match-muted"><strong>운송 구간</strong> {currentThread.request.region} → {currentThread.transport_to}</p>}
          {dealParticipant && (currentThread.deal_id || currentThread.can_start_deal) && <div className="deal-cta">
            {currentThread.deal_id ? <>
              <span>이 문의로 만든 거래 건이 있습니다.</span>
              <button type="button" className="primary-button" onClick={() => onOpenDeal?.(currentThread.deal_id!)}><Handshake size={16} /> 거래 건 열기</button>
            </> : <>
              <span>{currentThread.review?.status === 'accepted' ? '반입 가능으로 검토됐습니다. 단가·물량·운송 담당을 확정해 보세요.' : '조건이 맞으면 거래 건을 만들어 단가·물량·운송을 확정하세요.'}</span>
              <button type="button" className="primary-button" disabled={busy || !onOpenDeal} onClick={() => void startDeal(currentThread)}><Handshake size={16} /> 거래 건 만들기</button>
            </>}
          </div>}
          <div className="inbox-attachment">
            <button type="button" className="subtle-button" aria-expanded={preview} onClick={() => setPreview(!preview)}><FileText size={17} /> {preview ? '요청서 접기' : '첨부 요청서 열기'}</button>
            <button type="button" className="subtle-button" onClick={() => void api.downloadAttachment(currentThread.id).catch(failure => setError(getError(failure)))}><ArrowDownToLine size={16} /> Word 다운로드</button>
            {currentThread.attachments?.map(file => <button type="button" key={file.id} className="subtle-button"
              onClick={() => void api.downloadInquiryFile(currentThread.id, file).catch(failure => setError(getError(failure)))}>
              <Paperclip size={15} /> {file.name}
            </button>)}
          </div>
          {preview && <DocumentPreview request={currentThread.request} />}
          {currentThread.recipient_role === 'recycler' && <InquiryReviewPanel key={currentThread.id} inquiry={currentThread}
            canEdit={role === 'recycler' && workspace === currentThread.recipient_id} onSaved={review => {
              setThread(previous => previous?.id === currentThread.id ? { ...previous, review } : previous)
              setItems(previous => previous.map(item => item.id === currentThread.id ? { ...item, review } : item))
            }} />}
          <div className="inbox-messages" ref={contentBox} aria-label="문의 대화" aria-live="polite">
            {currentThread.messages.map(message => <div className={message.author_id === workspace ? 'outgoing' : ''} key={message.sequence}>
              <small>{message.author_id === workspace ? '나' : otherCompany(currentThread)} · {clock(message.created_at)}</small>
              <p>{message.content}</p>
            </div>)}
          </div>
          {error && <p className="match-error" role="alert">{error}</p>}
          <form className="inbox-composer" onSubmit={send}>
            <textarea aria-label="답장 내용" placeholder="답장을 입력하세요" rows={2} required maxLength={2000} disabled={busy} value={draft} onChange={e => setDraft(e.target.value)} />
            <button className="primary-button" type="submit" disabled={busy || !draft.trim()}><Send size={16} /> 답장 보내기</button>
          </form>
        </> : <div className="match-empty"><Inbox size={29} /><p>{selectedId ? '대화를 불러오는 중입니다…' : '목록에서 문의를 선택하세요.'}</p></div>}
      </section>
    </div>
  </section>
}
