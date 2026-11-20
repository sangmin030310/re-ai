import { useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent, type ReactNode } from 'react'
import {
  ArrowDownToLine, ArrowRight, ArrowUp, Check, Inbox, CheckCheck,
  CircleAlert, ClipboardList, Clock3, CloudUpload, File, FileArchive, FileSpreadsheet,
  FileText, FolderOpen, PanelRight, Leaf, Menu, MessageCircle, MoreHorizontal,
  PanelRightClose, Paperclip, Plus, Recycle, Settings, ShieldCheck, Sparkles, Trash2, X,
  BadgeCheck, Handshake, Megaphone,
} from 'lucide-react'
import { api, type Analysis, type Company, type CompanyRole, type CompanySession, type DocumentInfo, type IntakeRequest, type Message, type Project, type SupplyCriteria } from './lib/api'

import { canFindCompanies, Inquiries, Matching, type RequestDraftEditor } from './Matching'
import SupplyMarket from './SupplyMarket'
import AccountSettings from './AccountSettings'
import { DealsPage } from './Deals'
import { RecyclerDemands, SupplierDemands } from './Demands'
import { OperatorPermits } from './TrustSettings'

type Page = 'chat' | 'documents' | 'matching' | 'supply' | 'inquiries' | 'deals' | 'demands' | 'operator'
const pageNames = {
  documents: '문서 보관함', matching: '요청서 · 업체 찾기', inquiries: '기업 문의함',
  supply: '공급처 찾기', deals: '거래 건', demands: '수요 공고', operator: '허가 정보 확인',
}
const documentDate = new Intl.DateTimeFormat('ko-KR', {
  year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Seoul',
})
const formatDate = (date: string) => {
  const d = new Date(date)
  return Number.isNaN(d.getTime()) ? '' : documentDate.format(d)
}
const sizeLabel = (n: number) => n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`
const fieldNames: Record<string, string> = { material: '폐기물 재질', monthly_ton: '월간 발생량', contamination: '오염 여부' }
const chatByRole: Record<CompanyRole, {
  intro: string
  placeholder: string
  suggestions: { title: string; detail: string; prompt: string }[]
}> = {
  supplier: {
    intro: '폐기물 정보를 설명하면 요청서에 필요한 항목을 정리하고 가공업체를 찾을 수 있어요.',
    placeholder: '폐기물 정보를 입력하거나 요청서 작성을 부탁해 보세요',
    suggestions: [
      { title: '폐플라스틱 경로 분석', detail: 'PP 폐플라스틱 월 3톤', prompt: 'PP 폐플라스틱이 매월 3톤 발생합니다. 활용 경로를 검토해주세요.' },
      { title: '금속 부산물 검토', detail: '오염 없는 철스크랩', prompt: '오염 없음 상태의 철스크랩이 월 1톤 발생합니다. 어떤 경로가 있을까요?' },
      { title: '증빙 서류 정리', detail: '필요한 자료 확인', prompt: '폐기물 관련 서류와 증빙 자료를 어떻게 준비해야 하나요?' },
    ],
  },
  recycler: {
    intro: '필요한 재질과 물량을 알려주세요. 배출업체가 공개한 물량을 찾아볼 수 있어요.',
    placeholder: '예: 전주 근처에서 PP 2톤을 찾고 있어요',
    suggestions: [
      { title: '공개 물량 찾기', detail: '전주 지역 PP 2톤', prompt: '전주 근처에 공개된 PP 2톤을 찾아줘.' },
      { title: '수요 공고 올리기', detail: '공고에 넣을 항목 확인', prompt: '수요 공고를 어떻게 올려요?' },
      { title: '진행 중인 거래 확인', detail: '거래 단계와 다음 할 일', prompt: '진행 중인 거래 건을 알려줘.' },
    ],
  },
  carrier: {
    intro: '받은 운송 견적 요청과 진행 중인 운송 건을 물어보세요.',
    placeholder: '예: 내가 받은 운송 견적 요청이 있어요?',
    suggestions: [
      { title: '받은 견적 요청 확인', detail: '지금 답할 요청 찾기', prompt: '받은 운송 견적 요청이 몇 건이야?' },
      { title: '진행 중인 운송 건', detail: '운송 현황과 다음 할 일', prompt: '진행 중인 운송 건을 알려줘.' },
      { title: '상차 준비 확인', detail: '주소와 시간, 장비 확인', prompt: '상차 전에 어떤 정보를 확인해야 해?' },
    ],
  },
}

function RichText({ content }: { content: string }) {
  return <>{content.split('**').map((piece, index) => index % 2 ? <strong key={index}>{piece}</strong> : <span key={index}>{piece}</span>)}</>
}
function FileIcon({ name }: { name: string }) {
  const ext = name.split('.').pop()?.toLowerCase()
  if (ext === 'pdf') return <FileText size={19} color="#cc665b" />
  if (ext === 'xlsx' || ext === 'csv') return <FileSpreadsheet size={19} color="#438a72" />
  if (ext === 'zip') return <FileArchive size={19} color="#9876b7" />
  return <File size={19} color="#5d7894" />
}
function SectionHeading({ children, count }: { children: ReactNode; count?: number }) {
  return <div className="section-heading"><span>{children}</span>{count !== undefined && <span className="tiny-count">{count}</span>}</div>
}

export default function App({ onlineCompany, accountLogin = false, onSignOut, conversationalDraft = false, onChatGPTSettings, usingChatGPT = false }: {
  onlineCompany?: CompanySession
  accountLogin?: boolean
  onSignOut?: () => void
  conversationalDraft?: boolean
  onChatGPTSettings?: () => void
  usingChatGPT?: boolean
}) {
  const [projects, setProjects] = useState<Project[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [archiveDocuments, setArchiveDocuments] = useState<DocumentInfo[] | null>(null)
  const [archiveError, setArchiveError] = useState('')
  const [documentRevision, setDocumentRevision] = useState(0)
  const [page, setPage] = useState<Page>('chat')
  const [supplyFilters, setSupplyFilters] = useState<SupplyCriteria>()
  const [selectedDeal, setSelectedDeal] = useState<string | null>(null)
  const [intakeProject, setIntakeProject] = useState<string | null>(null)
  const [matchingProject, setMatchingProject] = useState<{ id: string; companies: Company[] } | null>(null)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [toast, setToast] = useState('')
  const [selectedInquiry, setSelectedInquiry] = useState<string | null>(null)
  const [workspaceInquiryOpen, setWorkspaceInquiryOpen] = useState(false)
  const workspace = onlineCompany?.id ?? 'local'
  const [panelOpen, setPanelOpen] = useState(() => window.innerWidth > 1100)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const scrollEnd = useRef<HTMLDivElement>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)
  const requestEditor = useRef<RequestDraftEditor>(null)
  const active = projects.find(p => p.id === activeId)
  const matchingFromChat = matchingProject?.id === activeId ? matchingProject : null
  const role = onlineCompany?.role ?? 'supplier'
  const canMatch = role === 'supplier'
  const canSource = accountLogin && role === 'recycler'
  const chat = chatByRole[role]
  const canOpenWorkspaceInquiry = accountLogin && role !== 'carrier'
  const workspaceThread = page === 'chat' && workspaceInquiryOpen && canOpenWorkspaceInquiry
  const analysisPanelAvailable = page === 'documents' || (page === 'chat' && canMatch && !workspaceThread)
  const intakeOpen = Boolean(canMatch && activeId && (intakeProject === activeId || canFindCompanies(active?.profile ?? {})))
  const latest = messages.at(-1)

  function openDeal(id: string) {
    setSelectedDeal(id)
    setWorkspaceInquiryOpen(false)
    setPage('deals')
    setSidebarOpen(false)
  }

  function openInquiry(id: string) {
    setSelectedInquiry(id)
    setWorkspaceInquiryOpen(canOpenWorkspaceInquiry)
    setPage(canOpenWorkspaceInquiry ? 'chat' : 'inquiries')
    setSidebarOpen(false)
  }

  const notify = (msg: string) => setToast(msg)

  useEffect(() => {
    if (!toast) return
    const timeout = window.setTimeout(() => setToast(''), 5000)
    return () => window.clearTimeout(timeout)
  }, [toast])

  const refreshProjects = async () => {
    const data = await api.projects()
    setProjects(data)
    return data
  }

  useEffect(() => {
    let cancelled = false
    api.projects().then(data => {
      if (cancelled) return
      setProjects(data)
      if (data.length) setActiveId(data[0].id)
      setLoading(false)
    }).catch(e => { if (!cancelled) { notify((e as Error).message); setLoading(false) } })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!activeId) { setMessages([]); setAnalysis(null); return }
    let cancelled = false
    setLoading(true)
    Promise.all([api.messages(activeId), api.analysis(activeId)])
      .then(([m, a]) => {
        if (cancelled) return
        setMessages(previous => Array.from(new Map([
          ...m, ...previous.filter(message => message.project_id === activeId && !message.id.startsWith('pending-')),
        ].map(message => [message.id, message])).values()))
        setAnalysis(a)
        setLoading(false)
      })
      .catch(e => { if (!cancelled) { notify((e as Error).message); setLoading(false) } })
    return () => { cancelled = true }
  }, [activeId])

  useEffect(() => {
    if (!activeId) { setDocuments([]); return }
    let cancelled = false
    api.documents(activeId).then(
      result => { if (!cancelled) setDocuments(result) },
      failure => { if (!cancelled) { setDocuments([]); setToast(failure.message) } },
    )
    return () => { cancelled = true }
  }, [activeId, documentRevision])

  useEffect(() => {
    if (page !== 'documents') return
    let cancelled = false
    setArchiveError('')
    api.documents().then(
      result => { if (!cancelled) setArchiveDocuments(result) },
      failure => { if (!cancelled) setArchiveError(failure.message) },
    )
    return () => { cancelled = true }
  }, [page, documentRevision])

  useEffect(() => { if (page === 'chat') scrollEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [messages, busy, page])

  const createProject = async (nextPage: Page = 'chat') => {
    try {
      const project = await api.createProject(canMatch ? undefined : '새 대화')
      setProjects(prev => [project, ...prev])
      setActiveId(project.id)
      setInput('')
      setWorkspaceInquiryOpen(false)
      setPage(nextPage)
      setSidebarOpen(false)
      if (nextPage === 'chat') setTimeout(() => textarea.current?.focus(), 100)
      return project.id
    } catch (e) { notify((e as Error).message) }
  }

  const switchProject = (id: string) => { setActiveId(id); setPage('chat'); setWorkspaceInquiryOpen(false); setInput(''); setSidebarOpen(false) }

  const rename = async (p: Project) => {
    const title = window.prompt('프로젝트 이름을 입력하세요.', p.title)?.trim()
    if (!title || title === p.title) return
    try { await api.renameProject(p.id, title); await refreshProjects(); notify('프로젝트 이름을 변경했습니다.') }
    catch (e) { notify((e as Error).message) }
  }

  const removeProject = async (p: Project) => {
    if (!window.confirm(`'${p.title}' 프로젝트와 연결된 대화 및 문서를 모두 삭제할까요?`)) return
    try {
      await api.deleteProject(p.id)
      setDocumentRevision(previous => previous + 1)
      const next = await refreshProjects()
      if (activeId === p.id) setActiveId(next[0]?.id || null)
      notify('프로젝트를 삭제했습니다.')
    } catch (e) { notify((e as Error).message) }
  }

  function syncRequest(request: IntakeRequest) {
    setProjects(previous => previous.map(project => project.id === activeId
      ? { ...project, profile: { ...project.profile, ...request } }
      : project))
    setDocumentRevision(previous => previous + 1)
    notify('요청서를 문서 보관함에 저장했습니다.')
  }

  const sendMessage = async (content = input, forceIntake = false, documentSelection?: string) => {
    const trimmed = content.trim()
    if (!trimmed || busy || loading) return
    const preparingRequest = canMatch && (forceIntake || intakeOpen || /(?:요청서|의뢰서)(?:만|를)?\s*(?:초안|작성|만들|써|도와)/.test(trimmed))
    setBusy(true)
    const projectId = activeId ?? await createProject()
    if (!projectId) { setBusy(false); return }
    if (preparingRequest) setIntakeProject(projectId)
    setInput('')
    const temp: Message = { id: `pending-${Date.now()}`, project_id: projectId, role: 'user', content: trimmed, actions: [], created_at: new Date().toISOString() }
    setMessages(prev => [...prev, temp])
    try {
      const draftEditor = requestEditor.current
      const draft = draftEditor?.projectId === projectId ? draftEditor.currentDraft() : undefined
      const result = await api.send(projectId, trimmed, preparingRequest, draft, documentSelection)
      setMessages(prev => prev.some(message => message.project_id !== projectId)
        ? prev
        : Array.from(new Map([...prev.filter(message => message.id !== temp.id), ...result.messages].map(message => [message.id, message])).values()))
      setAnalysis(result.analysis)
      setProjects(previous => previous.map(project => project.id === result.project.id ? result.project : project))
      const document = result.document_command
      const editor = requestEditor.current
      if (document?.saved_request && editor?.projectId === projectId) editor.recordSaved(document.saved_request)
      if (document?.changed) setDocumentRevision(previous => previous + 1)
      if (document?.open_archive) setPage('documents')
      void refreshProjects().catch(() => {})
    } catch (e) {
      setMessages(prev => prev.filter(m => m.id !== temp.id))
      setInput(trimmed)
      notify((e as Error).message)
    } finally { setBusy(false) }
  }

  function runChatAction(action: Message['actions'][number], forceIntake = false) {
    if (action.id === 'open-supply-market' && canSource) {
      const filters = active?.profile.supply_criteria as SupplyCriteria | undefined
      setSupplyFilters({ ...filters })
      setPage('supply')
      return
    }
    if (action.id === 'open-demands' && canSource) { setPage('demands'); return }
    if (action.id === 'open-deals') { setSelectedDeal(null); setPage('deals'); return }
    if (action.id.startsWith('archive-choice-') && action.value) {
      void sendMessage(`이 문서를 보관함에서 삭제해줘 · ${action.label}`, false, action.value)
    } else {
      void sendMessage(action.value || action.label, forceIntake)
    }
  }

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void sendMessage() }
  }

  const upload = async (files: FileList | null) => {
    if (!files || !files.length || !activeId) return
    let uploaded = 0
    for (const file of Array.from(files)) {
      try { await api.upload(activeId, file); uploaded++ }
      catch (e) { notify(`${file.name}: ${(e as Error).message}`) }
    }
    if (fileInput.current) fileInput.current.value = ''
    if (uploaded) {
      setDocumentRevision(previous => previous + 1)
      try { await refreshProjects(); notify(`${uploaded}개 파일을 보관함에 저장했습니다.`) }
      catch (e) { notify((e as Error).message) }
    }
  }

  const removeDocument = async (doc: DocumentInfo) => {
    if (!window.confirm(`'${doc.name}' 문서를 삭제하시겠습니까?`)) return
    try {
      await api.deleteDocument(doc.id)
      setDocumentRevision(previous => previous + 1)
      notify('문서를 삭제했습니다.')
    }
    catch (e) { notify((e as Error).message) }
  }

  const selectRoute = async (routeId: string) => {
    if (!activeId) return
    try { const result = await api.selectRoute(activeId, routeId); setAnalysis(result.analysis); await refreshProjects(); notify(result.notice) }
    catch (e) { notify((e as Error).message) }
  }

  const exportData = async () => {
    if (!activeId) return
    try {
      const data = await api.exportProject(activeId)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url; link.download = `ReAI_${activeId.slice(0, 8)}.json`; link.click()
      URL.revokeObjectURL(url)
    } catch (e) { notify((e as Error).message) }
  }

  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => { void upload(e.target.files) }

  const requestDraft = intakeOpen && activeId && <Matching
    embedded key={activeId} projectId={activeId} profile={active?.profile ?? {}} draftEditor={requestEditor}
    onCreate={() => createProject('chat')} onInquiry={openInquiry} onSaved={syncRequest} canPublish={accountLogin}
    onBrowse={companies => { setMatchingProject({ id: activeId, companies }); setPage('matching') }}
    chatBusy={busy} onOpenDeal={openDeal}
  />

  return <div className="app-shell">
    {sidebarOpen && <button className="mobile-shade" aria-label="메뉴 닫기" onClick={() => setSidebarOpen(false)} />}
    <aside className={`sidebar ${sidebarOpen ? 'sidebar-mobile-open' : ''}`}>
      <div className="brand-area">
        <div className="brand-mark"><Recycle size={23} strokeWidth={2.2} /></div>
        <div className="brand-titles"><b>Re<span className="brand-dot">.</span>AI</b><small>RESOURCE INTELLIGENCE</small></div>
        <button className="mobile-close icon-btn" onClick={() => setSidebarOpen(false)} aria-label="메뉴 닫기"><X size={18} /></button>
      </div>
      <button className="new-project" disabled={busy} onClick={() => void createProject()}><Plus size={18} /> {canMatch ? '새 분석 시작' : '새 대화 시작'} <span>+</span></button>
      <div className="nav-block">
        <div className="nav-label">WORKSPACE</div>
        <button className={`nav-link ${page === 'chat' ? 'active' : ''}`} onClick={() => { setPage('chat'); setWorkspaceInquiryOpen(false); setSidebarOpen(false) }}><MessageCircle size={18} /> AI 워크스페이스</button>
        <button className={`nav-link ${page === 'documents' ? 'active' : ''}`} onClick={() => { setPage('documents'); setSidebarOpen(false) }}><FolderOpen size={18} /> 문서 보관함</button>
        {canMatch && <button className={`nav-link ${page === 'matching' ? 'active' : ''}`} onClick={() => { if (page !== 'matching') setMatchingProject(null); setPage('matching'); setSidebarOpen(false) }}><ClipboardList size={18} /> 요청서 · 업체 찾기</button>}
        {canSource && <button className={`nav-link ${page === 'supply' ? 'active' : ''}`} onClick={() => { setPage('supply'); setSidebarOpen(false) }}><Recycle size={18} /> 공급처 찾기</button>}
        <button className={`nav-link ${page === 'inquiries' ? 'active' : ''}`} onClick={() => { setPage('inquiries'); setSidebarOpen(false) }}><Inbox size={18} /> 기업 문의함</button>
        <button className={`nav-link ${page === 'deals' ? 'active' : ''}`} onClick={() => { setPage('deals'); setWorkspaceInquiryOpen(false); setSidebarOpen(false) }}><Handshake size={18} /> 거래 건</button>
        {(canMatch || onlineCompany?.role === 'recycler') && <button className={`nav-link ${page === 'demands' ? 'active' : ''}`} onClick={() => { setPage('demands'); setWorkspaceInquiryOpen(false); setSidebarOpen(false) }}><Megaphone size={18} /> {canMatch ? '가공업체 수요 공고' : '우리 수요 공고'}</button>}
        {onlineCompany?.operator && <button className={`nav-link ${page === 'operator' ? 'active' : ''}`} onClick={() => { setPage('operator'); setWorkspaceInquiryOpen(false); setSidebarOpen(false) }}><BadgeCheck size={18} /> 허가 정보 확인</button>}
      </div>
      <div className="recent-block">
        <div className="recent-header"><span>최근 프로젝트</span><span className="rec-number">{projects.length}</span></div>
        <div className="recent-list">
          {projects.map(p => <div className={`project-item ${activeId === p.id ? 'selected' : ''}`} key={p.id}>
            <button className="project-name" onClick={() => switchProject(p.id)} title={p.title}>
              <span className="project-dot"/><span className="ellipsize">{p.title}</span>
            </button>
            <button className="project-more" title="이름 변경" onClick={() => void rename(p)}><MoreHorizontal size={17} /></button>
            <button className="project-delete" title="프로젝트 삭제" onClick={() => void removeProject(p)}><X size={14} /></button>
          </div>)}
          {!projects.length && <p className="no-projects">프로젝트가 없습니다.</p>}
        </div>
      </div>
      <div className="sidebar-bottom">
        <div className="tip-box"><span className="tip-icon"><Sparkles size={16}/></span><b>더 나은 자원순환의 시작</b><p>폐기물 정보를 입력하면 가능한 경로를 단계적으로 검토합니다.</p></div>
        {accountLogin && onlineCompany ? <button type="button" className="sidebar-profile sidebar-account-button"
          aria-haspopup="dialog" onClick={() => setSettingsOpen(true)}>
          <span className="profile-avatar" aria-hidden="true">{onlineCompany.label.slice(0, 1)}</span>
          <span className="sidebar-account-label"><b title={onlineCompany.label}>{onlineCompany.label}</b><small>프로필 설정</small></span>
          <Settings size={17} aria-hidden="true" />
        </button> : <div className="sidebar-profile"><div className="profile-avatar">R</div><div><b>Re AI Workspace</b><small>{onlineCompany ? "기업 작업공간" : "내 작업공간"}</small></div><span className="online-dot"/></div>}
      </div>
    </aside>

    <div className="main-wrap">
      <header className="topbar">
        <div className="topbar-left">
          <button className="icon-btn hamburger" onClick={() => setSidebarOpen(true)} aria-label="메뉴 열기"><Menu size={21}/></button>
          <div className="breadcrumb">워크스페이스 <span className="slash">/</span> <strong>{page === 'chat' ? workspaceThread ? '업체 대화' : (active?.title || 'AI 워크스페이스') : pageNames[page]}</strong></div>
        </div>
        <div className="topbar-actions">
          {onChatGPTSettings && <button className="subtle-button" onClick={onChatGPTSettings}>ChatGPT 설정</button>}
          {!accountLogin && onlineCompany && <div className="company-session"><strong>{onlineCompany.label}</strong><button className="subtle-button" onClick={onSignOut}>나가기</button></div>}
          <button title="프로젝트 데이터 내보내기" aria-label="내보내기" className="icon-btn hide-mobile" onClick={() => void exportData()} disabled={!activeId}><ArrowDownToLine size={19}/></button>
          {analysisPanelAvailable && <button className="icon-btn panel-toggle" title={panelOpen ? '분석 패널 닫기' : '분석 패널 열기'} onClick={() => setPanelOpen(v => !v)}>{panelOpen ? <PanelRightClose size={20}/> : <PanelRight size={20}/>}</button>}
        </div>
      </header>
      <div className="workspace-area">
        <main className={`content-area ${page === 'documents' ? 'content-documents' : ''}`}>
          {canSource && <SupplyMarket visible={page === 'supply'} preset={supplyFilters} onInquiry={openInquiry}
            onOpenConversations={() => setPage('inquiries')} />}
          {page === 'supply' ? null
          : page === 'matching' ? <Matching key={activeId ?? 'empty'} projectId={activeId} profile={active?.profile ?? {}} onCreate={() => createProject('matching')} onInquiry={openInquiry} onSaved={syncRequest} canPublish={accountLogin && canMatch} initialCompanies={matchingFromChat?.companies} onBackToChat={matchingFromChat ? () => { setMatchingProject(null); setPage('chat') } : undefined} onOpenDeal={openDeal} />
          : page === 'deals' ? <DealsPage workspace={workspace} role={onlineCompany?.role ?? 'supplier'} selectedId={selectedDeal} onSelect={setSelectedDeal} onOpenInquiry={openInquiry} />
          : page === 'demands' ? (canMatch ? <SupplierDemands projects={projects} activeId={activeId} onInquiry={openInquiry} />
            : <RecyclerDemands onOpenInquiries={() => setPage('inquiries')} />)
          : page === 'operator' ? <OperatorPermits />
          : page === 'inquiries' || workspaceThread ? <Inquiries workspace={workspace} role={onlineCompany?.role ?? 'supplier'} selectedId={selectedInquiry} onSelect={setSelectedInquiry}
            onBackToWorkspace={workspaceThread ? () => setWorkspaceInquiryOpen(false) : undefined} onOpenDeal={openDeal} />
          : page === 'chat' ? <>
            <div className="chat-heading"><div><div className="eyebrow">AI WORKSPACE</div><h1>{active?.title || '자원순환 워크스페이스'}</h1>{canMatch && <div className="heading-sub"><span className="heading-dot"/> {analysis?.stage || '새 분석 대기'}</div>}</div><button className="subtle-button" onClick={() => void exportData()} disabled={!activeId}><ArrowDownToLine size={16}/> {canMatch ? '분석 내역 저장' : '대화 내역 저장'}</button></div>
            {(canOpenWorkspaceInquiry || (canMatch && !intakeOpen) || role === 'carrier') && <div className="chat-match-action">
              {canMatch && !intakeOpen && <button className="subtle-button" disabled={busy || loading} onClick={() => void sendMessage('폐기물 요청서 작성 도와줘', true)}>
                <FileText size={16} /> 폐기물 요청서 작성 <ArrowRight size={15} />
              </button>}
              {canSource && <button className="subtle-button" onClick={() => setPage('supply')}><Recycle size={16} /> 공급처 찾기</button>}
              {role === 'carrier' && <button className="subtle-button" onClick={() => { setSelectedDeal(null); setPage('deals') }}><Handshake size={16} /> 받은 견적 요청 및 운송 건</button>}
              {canOpenWorkspaceInquiry && <button className="subtle-button" onClick={() => setWorkspaceInquiryOpen(true)}><Inbox size={16} /> 업체 대화 보기</button>}
            </div>}
            <div className="chat-scroller">
              {loading ? <div className="loading-state">프로젝트를 불러오는 중입니다…</div> : messages.length ? <div className="messages">
                <div className="day-divider"><span>최근 대화</span></div>
                {messages.map((msg, idx) => <div className={`message-row ${msg.role}`} key={msg.id}>
                  {msg.role === 'assistant' && <div className="assistant-avatar"><Leaf size={17}/></div>}
                  <div className="message-column">
                    {msg.role === 'assistant' && <div className="message-author">Re AI <span>분석 어시스턴트</span></div>}
                    <div className="message-bubble"><RichText content={msg.content}/></div>
                    {(!intakeOpen || conversationalDraft) && msg.role === 'assistant' && msg.actions?.length > 0 && idx === messages.length - 1 && <div className="action-chips">{msg.actions.map(action => <button key={action.id} disabled={busy} onClick={() => runChatAction(action)}>{action.label}<ArrowRight size={14}/></button>)}</div>}
                    <span className="message-time">{new Date(msg.created_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                </div>)}
                {busy && <div className="message-row assistant"><div className="assistant-avatar"><Leaf size={17}/></div><div className="message-column"><div className="message-author">Re AI</div><div className="typing-bubble"><i/><i/><i/></div></div></div>}

              </div> : <div className="welcome">
                <div className="welcome-icon"><Sparkles size={27}/></div>
                <span className="welcome-kicker">SMART CIRCULAR ECONOMY</span>
                <h2>버려지는 자원에<br/><em>새로운 가능성을.</em></h2>
                <p>{chat.intro}</p>
                <div className="suggestions">{chat.suggestions.map(item => <button key={item.title} onClick={() => void sendMessage(item.prompt)}><span className="suggestion-icon"><ArrowRight size={17}/></span><b>{item.title}</b><small>{item.detail}</small></button>)}</div>
              </div>}
              {!loading && requestDraft}
              <div ref={scrollEnd}/>
            </div>
            <div className="composer-wrap">
              {intakeOpen && !conversationalDraft && !busy && latest?.project_id === activeId && latest.role === 'assistant' && <div className="request-chat-prompt">
                <RichText content={latest.content} />
                {latest.actions.length > 0 && <div className="action-chips">{latest.actions.map(action => <button key={action.id} onClick={() => runChatAction(action, true)}>{action.label}<ArrowRight size={14}/></button>)}</div>}
              </div>}
              {conversationalDraft && busy && <p className="request-chat-prompt" role="status">Re AI가 대화를 읽고 답변을 작성하고 있어요.</p>}
              <div className="composer"><textarea ref={textarea} value={input} rows={2} disabled={busy || loading} placeholder={intakeOpen ? "질문에 답하거나 수정할 항목을 입력하세요" : chat.placeholder} onChange={e => setInput(e.target.value)} onKeyDown={handleKey} aria-label="메시지 입력"/><div className="composer-footer"><div className="composer-tools"><button onClick={() => fileInput.current?.click()} disabled={!activeId} title="파일 첨부"><Paperclip size={17}/> <span>파일 첨부</span></button><span className="composer-hint">Enter 전송 · Shift+Enter 줄바꿈</span></div><button className="send-btn" disabled={!input.trim() || busy || loading} onClick={() => void sendMessage()} aria-label="메시지 전송"><ArrowUp size={19}/></button></div></div>
              {onChatGPTSettings && <p className="composer-note">
                {usingChatGPT ? 'ChatGPT 구독 사용 중' : 'ChatGPT 연결 필요'}
                {usingChatGPT ? <a href="https://chatgpt.com/#settings/Usage" target="_blank" rel="noreferrer">사용량 관리</a>
                  : <button className="subtle-button" onClick={onChatGPTSettings}>연결 설정</button>}
              </p>}
              <p className="composer-note"><ShieldCheck size={13}/> AI 분석 결과는 참고용입니다. 최종 판단은 사용자와 관련 전문가의 검증이 필요합니다.</p>
            </div>
          </> : <div className="docs-page">
            <div className="docs-eyebrow">DOCUMENT CENTER</div><div className="docs-title-row"><div><h1>문서 보관함</h1><p>프로젝트의 입력 자료와 관련 서류를 한곳에서 관리합니다.</p></div><button className="primary-button" onClick={() => fileInput.current?.click()} disabled={!activeId}><Plus size={18}/> 문서 업로드</button></div>
            <div className="docs-summary"><div className="docs-summary-icon"><FolderOpen size={23}/></div><div><b>전체 프로젝트 문서</b><span>{archiveDocuments ? `${archiveDocuments.length}개 저장됨` : '문서 목록'}</span></div><span className="docs-project-label">{active ? `업로드 대상 · ${active.title}` : '프로젝트를 선택하면 업로드할 수 있습니다.'}</span></div>
            <button className="upload-zone" onClick={() => fileInput.current?.click()} disabled={!activeId} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (e.dataTransfer.files.length) void upload(e.dataTransfer.files) }}><CloudUpload size={31}/><b>여기에 파일을 놓거나 클릭해서 업로드</b><small>PDF, HWP/HWPX, DOCX, XLSX, 이미지, TXT, CSV · 최대 15MB</small></button>
            <div className="file-list-head"><h2>저장된 문서 {archiveDocuments && <span>{archiveDocuments.length}</span>}</h2><span>최근 저장순</span></div>
            <div className="file-list">
              {archiveError ? <div className="empty-files" role="alert"><b>{archiveError}</b><button type="button" className="subtle-button" onClick={() => setDocumentRevision(previous => previous + 1)}>다시 불러오기</button></div>
                : !archiveDocuments ? <p role="status">문서를 불러오는 중입니다…</p>
                : archiveDocuments.length ? archiveDocuments.map(doc => <div className="file-row" key={doc.id}>
                  <div className="file-icon"><FileIcon name={doc.name}/></div>
                  <div className="file-meta">
                    <b title={doc.name}>{doc.name}</b>
                    <span>{doc.project_title || projects.find(project => project.id === doc.project_id)?.title || '프로젝트'}</span>
                    <span>{doc.source === 'request' ? '자동 보관 · ' : doc.size !== null ? `${sizeLabel(doc.size)} · ` : ''}{formatDate(doc.created_at)} {doc.source === 'request' ? '저장' : '등록'}</span>
                  </div>
                  <button type="button" title="다운로드" aria-label={`${doc.name} 다운로드`} className="doc-action" onClick={() => void api.downloadDocument(doc.id, doc.name).catch(e => notify((e as Error).message))}><ArrowDownToLine size={18}/></button>
                  <button type="button" title="삭제" aria-label={`${doc.name} 삭제`} className="doc-action danger" onClick={() => void removeDocument(doc)}><Trash2 size={17}/></button>
                </div>) : <div className="empty-files"><FileText size={26}/><b>아직 보관한 문서가 없습니다.</b><span>요청서를 저장하면 여기에 표시됩니다.</span></div>}
            </div>
            <p className="docs-warning"><CircleAlert size={15}/> 현재는 로컬 시연용 저장소입니다. 기업의 민감한 서류를 실제로 올리기 전 로그인·접근 권한·보안 설정이 필요합니다.</p>
          </div>}
        </main>

        {panelOpen && analysisPanelAvailable && <aside className="insight-panel">
          <div className="insight-title"><div><span className="insight-kicker">ANALYSIS STATUS</span><h2>분석 현황</h2></div><div className="insight-status"><span/> {analysis?.stage || '대기 중'}</div></div>
          <div className="panel-scroll">
            <div className="panel-section"><SectionHeading>검토 진행 단계</SectionHeading><div className="steps-list">{(analysis?.steps || [{label:'배출 정보 입력',state:'current' as const},{label:'필수 정보 검토',state:'waiting' as const},{label:'활용 경로 비교',state:'waiting' as const},{label:'업체 및 증빙 확인',state:'waiting' as const},{label:'사용자 최종 선택',state:'waiting' as const}]).map((step,idx) => <div className={`step-item ${step.state}`} key={step.label}><div className="step-marker">{step.state === 'done' ? <Check size={13} strokeWidth={3}/> : idx+1}</div><span>{step.label}</span>{step.state === 'current' && <b>진행 중</b>}</div>)}</div></div>
            <div className="panel-section"><SectionHeading>폐기물 정보</SectionHeading><div className="info-card"><div><span>재질 / 종류</span><b>{analysis?.profile.material || '미입력'}</b></div><div><span>월간 발생량</span><b>{analysis?.profile.monthly_ton ? `${analysis.profile.monthly_ton} 톤` : '미입력'}</b></div><div><span>오염 여부</span><b className="value-small">{analysis?.profile.contamination || '확인 필요'}</b></div></div>{!!analysis?.missing_fields.length && <p className="missing-note"><CircleAlert size={14}/> 추가 정보 {analysis.missing_fields.map(key => fieldNames[key] || key).join(', ')} 필요</p>}</div>
            <div className="panel-section"><SectionHeading count={analysis?.routes.length || 0}>활용 경로 후보</SectionHeading>{analysis?.routes.length ? <div className="routes">{analysis.routes.map((r, i) => <div className={`route-card ${analysis.selected_route === r.id ? 'chosen' : ''}`} key={r.id}><div className="route-line"><span className="route-index">0{i+1}</span><span className="route-tag">{analysis.selected_route === r.id ? '선택됨' : r.tag}</span></div><b>{r.title}</b><p>{r.detail}</p><div className="route-tags">{r.checks.map(c => <span key={c}>{c}</span>)}</div><button onClick={() => void selectRoute(r.id)} disabled={analysis.selected_route === r.id}>{analysis.selected_route === r.id ? <><CheckCheck size={14}/> 임시 선택됨</> : <>후보 선택 <ArrowRight size={14}/></>}</button></div>)}</div> : <div className="routes-empty"><ClipboardList size={21}/><b>경로 검토 대기 중</b><span>재질·발생량·오염 정보를 확인하면 검토 후보가 표시됩니다.</span></div>}</div>
            <div className="panel-section panel-doc-section"><SectionHeading count={documents.length}>연결된 문서</SectionHeading>{documents.slice(0,3).map(doc => <div className="panel-document" key={doc.id}><FileIcon name={doc.name}/><span title={doc.name}>{doc.name}</span></div>)}<button className="panel-doc-button" onClick={() => setPage('documents')}><FolderOpen size={15}/> 문서 보관함 열기 <ArrowRight size={14}/></button></div>
          </div>
          <div className="panel-footer"><Clock3 size={14}/> 모든 분석은 데모 기준이며 검증이 필요합니다.</div>
        </aside>}
      </div>
    </div>
    {settingsOpen && accountLogin && onlineCompany && <AccountSettings company={onlineCompany}
      onClose={() => setSettingsOpen(false)} onSignOut={onSignOut} />}
    <input ref={fileInput} type="file" accept=".pdf,.png,.jpg,.jpeg,.docx,.xlsx,.txt,.csv,.hwp,.hwpx" multiple hidden onChange={onFileChange}/>
    {toast && <div className="toast" role="status"><span>{toast}</span><button aria-label="알림 닫기" onClick={() => setToast('')}><X size={16}/></button></div>}
  </div>
}
