import { useEffect, useState, type FormEvent } from 'react'
import { api } from './lib/api'

export type RecoveryMode = 'setup' | 'username' | 'forgot' | 'verify' | 'reset'

const titles: Record<RecoveryMode, string> = {
  setup: '복구 이메일 등록',
  username: '아이디 찾기',
  forgot: '비밀번호 재설정',
  verify: '복구 이메일 인증',
  reset: '새 비밀번호 설정',
}

const messages: Record<RecoveryMode, string> = {
  setup: '인증 메일을 보냈습니다. 메일의 링크에서 인증을 완료해 주세요.',
  username: '등록된 이메일 주소라면 아이디 안내 메일이 도착합니다.',
  forgot: '등록된 이메일 주소라면 재설정 메일이 도착합니다.',
  verify: '이메일 인증을 완료했습니다. 이 주소로 계정을 복구할 수 있습니다.',
  reset: '비밀번호를 변경했습니다. 새 비밀번호로 로그인해 주세요.',
}

export default function AccountRecovery({ mode, token, signedIn, onClose, embedded = false }: {
  mode: RecoveryMode
  token?: string
  signedIn: boolean
  onClose: () => void
  embedded?: boolean
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const [emailState, setEmailState] = useState<Awaited<ReturnType<typeof api.recoveryEmail>> | null>(null)
  const [changeEmail, setChangeEmail] = useState(false)
  const pendingEmail = mode === 'setup' ? emailState?.pending_email : null
  const sendPending = Boolean(pendingEmail && !changeEmail)
  const canSubmit = mode !== 'setup' || Boolean(emailState && (!sendPending || emailState.mail_available))

  useEffect(() => {
    if (mode !== 'setup') return
    let active = true
    api.recoveryEmail().then(
      result => { if (active) setEmailState(result) },
      failure => { if (active) setError(failure.message) },
    )
    return () => { active = false }
  }, [mode])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !canSubmit) return
    const form = new FormData(event.currentTarget)
    const email = String(form.get('email') ?? '').trim()
    const password = String(form.get('password') ?? '')
    if (mode === 'reset' && password !== form.get('confirm')) {
      setError('새 비밀번호가 서로 다릅니다.')
      return
    }
    setBusy(true)
    setError('')
    try {
      if (mode === 'setup') {
        if (sendPending) await api.sendPendingEmail()
        else {
          const result = await api.setRecoveryEmail(email, password)
          setEmailState(previous => previous && { ...previous, pending_email: email })
          setChangeEmail(false)
          if (!result.mail_sent) {
            setError(result.message || '이메일을 저장했습니다. 인증 메일은 나중에 다시 요청해 주세요.')
            return
          }
        }
      }
      if (mode === 'username' || mode === 'forgot') await api.requestRecovery(email, mode === 'username' ? 'username' : 'reset')
      if (mode === 'verify') await api.verifyRecoveryEmail(token ?? '')
      if (mode === 'reset') await api.resetPassword(token ?? '', password)
      setDone(true)
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const emailInput = (mode === 'setup' && !sendPending) || mode === 'username' || mode === 'forgot'
  const content = <section className={embedded ? 'account-settings-recovery' : 'match-card'}>
      {embedded ? <h3>복구 이메일 관리</h3> : <h1>{titles[mode]}</h1>}
      {mode === 'setup' && !emailState && !error && <p role="status">복구 이메일을 확인하는 중입니다…</p>}
      {mode === 'setup' && emailState?.email && <p>인증된 복구 이메일 <strong>{emailState.email}</strong></p>}
      {pendingEmail && <p>인증 대기 중인 이메일 <strong>{pendingEmail}</strong></p>}
      {mode === 'setup' && emailState && !emailState.mail_available && <p role="status">
        지금은 복구 이메일 주소를 저장할 수 있습니다. 인증 메일은 서버의 메일 발송 설정이 준비되면 요청할 수 있습니다.
      </p>}
      {mode === 'verify' && !done && <p>이 이메일 주소를 Re AI 계정 복구에 사용하려면 인증을 완료해 주세요.</p>}
      {done ? <p role="status">{messages[mode]}</p> : canSubmit && <form className="match-form" onSubmit={submit}>
        <fieldset disabled={busy}>
          {emailInput && <label>{mode === 'setup' && (emailState?.email || pendingEmail) ? '새 복구 이메일' : '복구 이메일'}
            <input name="email" type="email" autoComplete="email" required maxLength={254} />
          </label>}
          {((mode === 'setup' && !sendPending) || mode === 'reset') && <label>{mode === 'setup' ? 'Re AI 로그인 비밀번호' : '새 비밀번호'}
            <input name="password" type="password" autoComplete={mode === 'setup' ? 'current-password' : 'new-password'}
              required minLength={8} maxLength={128} />
          </label>}
          {mode === 'reset' && <label>새 비밀번호 확인
            <input name="confirm" type="password" autoComplete="new-password" required minLength={8} maxLength={128} />
          </label>}
          <button className="primary-button" type="submit">
            {busy ? '처리 중…' : mode === 'verify' ? '인증 완료하기' : mode === 'reset' ? '비밀번호 변경' :
              mode === 'setup' ? (emailState?.mail_available ? '인증 메일 보내기' : '이메일 주소 저장') : '메일 보내기'}
          </button>
        </fieldset>
      </form>}
      {error && <p className="match-error" role="alert">{error}</p>}
      {(!embedded || (pendingEmail && !done)) && <div className="account-switch">
        {pendingEmail && !done && <button className="subtle-button" type="button" disabled={busy} onClick={() => {
          setError('')
          setChangeEmail(!changeEmail)
        }}>{changeEmail ? '기존 주소 사용' : '이메일 주소 변경'}</button>}
        {!embedded && <button className="subtle-button" type="button" disabled={busy} onClick={onClose}>
          {signedIn && !(mode === 'reset' && done) ? '작업공간으로 돌아가기' : '로그인 화면으로 돌아가기'}
        </button>}
      </div>}
    </section>
  return embedded ? content : <main className="online-entry">{content}</main>
}
