import { useEffect, useState, type FormEvent } from 'react'
import { ArrowRight, Eye, EyeOff, Recycle } from 'lucide-react'
import AccountEntry from './AccountEntry'
import AccountRecovery, { type RecoveryMode } from './AccountRecovery'
import App from './App'
import { api, type CompanySession } from './lib/api'

type ChatGPTStatus = Awaited<ReturnType<typeof api.chatGPTStatus>>
type RecoveryView = { mode: RecoveryMode; token?: string }
const chatGPTUsage = 'https://chatgpt.com/#settings/Usage'

function recoveryLink(): RecoveryView | null {
  const params = new URLSearchParams(window.location.hash.slice(1))
  const mode = params.get('recovery')
  const token = params.get('token')
  return (mode === 'verify' || mode === 'reset') && token && /^[a-zA-Z0-9_-]{43}$/.test(token) ? { mode, token } : null
}

export default function OnlineEntry() {
  const [online, setOnline] = useState<boolean | null>(null)
  const [company, setCompany] = useState<CompanySession | null>(null)
  const [code, setCode] = useState('')
  const [pcShare, setPcShare] = useState(false)
  const [accountLogin, setAccountLogin] = useState(false)
  const [recovery, setRecovery] = useState(recoveryLink)
  const [conversationalDraft, setConversationalDraft] = useState(false)
  const [chatGPT, setChatGPT] = useState<ChatGPTStatus | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [models, setModels] = useState<{ slug: string; name: string }[]>([])
  const [showWelcome, setShowWelcome] = useState(false)
  const [showCode, setShowCode] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    function openRecoveryLink() { setRecovery(recoveryLink()) }
    window.addEventListener('hashchange', openRecoveryLink)
    return () => window.removeEventListener('hashchange', openRecoveryLink)
  }, [])

  useEffect(() => {
    let ignore = false
    async function load() {
      try {
        const { online_demo: enabled, pc_share: sharingFromPc, account_login: accounts, mode } = await api.health()
        if (ignore) return
        setPcShare(Boolean(sharingFromPc))
        setAccountLogin(Boolean(accounts))
        if (accounts) sessionStorage.removeItem('reai_invite')
        setConversationalDraft(mode === 'openai' || mode === 'chatgpt')
        if (mode === 'chatgpt') {
          const status = await api.chatGPTStatus()
          if (ignore) return
          setChatGPT(status)
          const callback = new URLSearchParams(window.location.search).get('chatgpt')
          if (callback) {
            window.history.replaceState(null, '', window.location.pathname)
            setShowSettings(true)
            setShowWelcome(callback === 'welcome')
            if (callback === 'error') setError('ChatGPT 로그인을 확인하지 못했습니다. 다시 시도해 주세요.')
            if (callback === 'denied') setError('ChatGPT 연결을 취소했습니다.')
            if (callback === 'permission') setError('ChatGPT 구독을 쓰려면 로그인할 때 구독 사용을 허용해 주세요.')
          }
        }
        if (enabled && (accounts || sessionStorage.getItem('reai_invite'))) {
          const session = await api.session().catch(() => null)
          if (ignore) return
          if (session) setCompany(session)
          else sessionStorage.removeItem('reai_invite')
        }
        setOnline(Boolean(enabled))
      } catch (failure) {
        if (!ignore) setError((failure as Error).message)
      }
    }
    void load()
    return () => { ignore = true }
  }, [])

  async function enter(event: FormEvent) {
    event.preventDefault()
    if (busy || !code.trim()) return
    setBusy(true)
    setError('')
    sessionStorage.setItem('reai_invite', code.trim())
    try {
      setCompany(await api.session())
      setCode('')
      setShowCode(false)
    } catch (failure) {
      sessionStorage.removeItem('reai_invite')
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function signOut() {
    if (busy) return
    setBusy(true)
    try {
      if (accountLogin) await api.logout()
      sessionStorage.removeItem('reai_invite')
      setCompany(null)
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function changeChatGPT(action: () => Promise<void>) {
    setBusy(true)
    setError('')
    try { await action() }
    catch (failure) { setError((failure as Error).message) }
    finally { setBusy(false) }
  }

  async function openChatGPTSettings() {
    setShowSettings(true)
    await changeChatGPT(async () => {
      setChatGPT(await api.chatGPTStatus())
      setModels([])
    })
  }

  async function connectChatGPT(clientId?: string) {
    await changeChatGPT(async () => {
      const { url } = await api.connectChatGPT(clientId)
      window.location.assign(url)
    })
  }

  async function closeRecovery() {
    if (recovery?.token) {
      window.history.replaceState(null, '', window.location.pathname + window.location.search)
      if (recovery.mode === 'reset') setCompany(await api.session().catch(() => null))
    }
    setRecovery(null)
  }

  if (online && accountLogin && recovery) return <AccountRecovery key={recovery.token ?? recovery.mode}
    mode={recovery.mode} token={recovery.token}
    signedIn={Boolean(company)} onClose={() => void closeRecovery()} />

  if (chatGPT && showSettings) return <main className="online-entry">
    <section className="match-card">
      <h1>ChatGPT 연결</h1>
      <p>요청서 채팅에서 지원되는 AI 요청에 본인의 ChatGPT 구독 사용량을 쓸 수 있습니다.</p>
      {showWelcome && <div className="match-form" role="status">
        <strong>ChatGPT 구독을 연결했습니다.</strong>
        <p>사용량과 한도는 ChatGPT 설정에서 확인할 수 있습니다.</p>
        <button className="subtle-button" onClick={() => setShowWelcome(false)}>확인</button>
      </div>}
      {chatGPT.email && <p><strong>{chatGPT.email}</strong> · {chatGPT.enabled ? '구독 사용 연결됨' : '구독 권한 확인 필요'}</p>}
      <div className="match-form">
        {!chatGPT.enabled && <button className="primary-button" disabled={busy} onClick={() => void connectChatGPT(chatGPT.active ?? undefined)}>Continue with ChatGPT</button>}
        {chatGPT.accounts.filter(account => account.id !== chatGPT.active).map(account => (
          <button key={account.id} className="subtle-button" disabled={busy} onClick={() => void connectChatGPT(account.id)}>
            {account.email} · {account.id.slice(-6)}로 계속하기
          </button>
        ))}
        {chatGPT.accounts.length > 0 && <button className="subtle-button" disabled={busy} onClick={() => void connectChatGPT()}>다른 ChatGPT 계정 연결</button>}
        {chatGPT.enabled && <>
          {models.length ? <label>사용 모델<select disabled={busy} value={chatGPT.model ?? ''} onChange={event => {
            const selected = event.target.value
            if (selected) void changeChatGPT(async () => {
              await api.selectChatGPTModel(selected)
              setChatGPT(await api.chatGPTStatus())
            })
          }}>
            <option value="" disabled>자동 선택</option>
            {models.map(model => <option key={model.slug} value={model.slug}>{model.name}</option>)}
          </select></label>
            : <button className="subtle-button" disabled={busy} onClick={() => void changeChatGPT(async () => setModels(await api.chatGPTModels()))}>사용 모델 고르기</button>}
          <a href={chatGPTUsage} target="_blank" rel="noreferrer">ChatGPT 사용량 관리</a>
          <button className="subtle-button" disabled={busy} onClick={() => void changeChatGPT(async () => {
            const result = await api.disconnectChatGPT()
            setChatGPT(await api.chatGPTStatus())
            setModels([])
            setShowWelcome(false)
            if (!result.revoked) setError('이 PC에서 연결을 해제했습니다. ChatGPT 설정에서도 연결 해제 여부를 확인해 주세요.')
          })}>ChatGPT 연결 해제</button>
        </>}
        {error && <p className="match-error" role="alert">{error}</p>}
        <button className="primary-button" disabled={busy} onClick={() => { setShowSettings(false); setShowWelcome(false); setError('') }}>Re AI로 돌아가기</button>
      </div>
    </section>
  </main>

  if (company) return <>
    <App key={company.id} onlineCompany={company} accountLogin={accountLogin} onSignOut={() => void signOut()} conversationalDraft={conversationalDraft}
      onChatGPTSettings={chatGPT && company.role === 'supplier' ? () => void openChatGPTSettings() : undefined} usingChatGPT={Boolean(chatGPT?.enabled)} />
    {error && <div className="toast" role="alert">{error}</div>}
  </>
  if (online === false) return <App conversationalDraft={conversationalDraft} />

  return <main className="online-entry">
    <section className="match-card">
      <div className="market-symbol"><Recycle size={25} /></div>
      <h1>Re AI 기업 작업공간</h1>
      {online && accountLogin ? <AccountEntry onEnter={setCompany} onRecovery={mode => setRecovery({ mode })} /> : online ? <form className="match-form" onSubmit={enter}>
        <div className="invite-field">
          <label htmlFor="company-invite">기업 초대 코드</label>
          <div className="invite-input">
            <input id="company-invite" type={showCode ? 'text' : 'password'} required value={code}
              placeholder={pcShare ? 'XXXX-XXXX-XXXX' : undefined} autoCapitalize="characters" spellCheck={false}
              aria-describedby={pcShare ? 'company-invite-hint' : undefined} onChange={event => setCode(event.target.value)} />
            <button type="button" className="subtle-button" onClick={() => setShowCode(previous => !previous)} aria-label={showCode ? '코드 숨기기' : '코드 보기'}>
              {showCode ? <EyeOff size={17} /> : <Eye size={17} />}
            </button>
          </div>
          {pcShare && <small id="company-invite-hint">소문자로 입력하거나 하이픈을 빼도 됩니다.</small>}
        </div>
        <button className="primary-button" disabled={busy || !code.trim()}>작업공간 열기 <ArrowRight size={17} /></button>
        {chatGPT && <button type="button" className="subtle-button" disabled={busy} onClick={() => void openChatGPTSettings()}>ChatGPT 설정</button>}
      </form> : !error && <p>서버에 연결하는 중입니다…</p>}
      {error && <p className="match-error" role="alert">{error}</p>}
      {online === null && error && <button className="subtle-button" onClick={() => window.location.reload()}>다시 연결</button>}
    </section>
  </main>
}
