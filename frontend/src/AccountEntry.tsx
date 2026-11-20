import { useRef, useState, type FormEvent } from 'react'
import { ArrowRight } from 'lucide-react'
import { api, materials, type CompanyRole, type CompanySession } from './lib/api'

export default function AccountEntry({ onEnter, onRecovery }: {
  onEnter: (company: CompanySession) => void
  onRecovery: (mode: 'username' | 'forgot') => void
}) {
  const [creating, setCreating] = useState(false)
  const [role, setRole] = useState<CompanyRole>('supplier')
  const [busy, setBusy] = useState(false)
  const [sendingCode, setSendingCode] = useState(false)
  const [challenge, setChallenge] = useState('')
  const [emailCode, setEmailCode] = useState('')
  const [error, setError] = useState('')
  const emailInput = useRef<HTMLInputElement>(null)
  const recycler = creating && role === 'recycler'
  const carrier = creating && role === 'carrier'

  async function sendCode() {
    const input = emailInput.current
    if (busy || sendingCode || !input?.reportValidity()) return
    setSendingCode(true)
    setError('')
    try {
      const result = await api.sendSignupEmailCode(input.value.trim())
      setChallenge(result.challenge_id)
      setEmailCode('')
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setSendingCode(false)
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || sendingCode || (creating && !challenge)) return
    const details = new FormData(event.currentTarget)
    const read = (key: string) => String(details.get(key) ?? '')
    const credentials = { username: read('username').trim(), password: read('password') }
    const company_name = read('company_name').trim()
    const recoveryEmail = read('recovery_email').trim()
    const city = read('city').trim()
    const regions = read('regions').split(',').map(region => region.trim()).filter(Boolean)
    const accepted = details.getAll('material').map(String)
    const minimum = read('min_ton')
    if ((recycler || carrier) && !accepted.length) {
      setError('취급 재질을 하나 이상 선택해 주세요.')
      return
    }
    if (recycler && minimum && Number(minimum) > Number(read('max_ton'))) {
      setError('월 최소 반입량은 최대 수용량 이하여야 합니다.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const profile = {
        city, regions: [...new Set([city, ...regions])], materials: accepted,
        max_ton: Number(read('max_ton')),
      }
      const account = creating ? await api.register({
        ...credentials, company_name, role, recovery_email: recoveryEmail,
        signup_email_challenge: challenge, signup_email_code: emailCode,
        recycler_profile: recycler ? { ...profile, transport: read('transport'), min_ton: minimum ? Number(minimum) : undefined } : undefined,
        carrier_profile: carrier ? profile : undefined,
      }) : await api.login(credentials)
      onEnter(account)
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return <>
    <form key={creating ? 'register' : 'login'} className="match-form" onSubmit={submit}>
      <fieldset disabled={busy || sendingCode}>
        {creating && <>
          <label>업체 유형<select value={role} onChange={event => setRole(event.target.value as CompanyRole)}>
            <option value="supplier">배출업체</option>
            <option value="recycler">가공업체</option>
            <option value="carrier">운송업체</option>
          </select></label>
          <label>업체 이름<input name="company_name" required minLength={2} maxLength={60} placeholder="예: 한빛부품" /></label>
          <label>이메일<input ref={emailInput} name="recovery_email" type="email" required maxLength={254}
            autoComplete="email" placeholder="예: company@gmail.com" onChange={() => {
              setChallenge('')
              setEmailCode('')
              setError('')
            }} /></label>
          <button type="button" className="subtle-button" onClick={() => void sendCode()}>
            {sendingCode ? '인증번호 보내는 중…' : challenge ? '인증번호 다시 보내기' : '인증번호 보내기'}
          </button>
          {challenge && <>
            <p role="status">이메일에 보낸 인증번호를 10분 안에 입력해 주세요.</p>
            <label>이메일 인증번호<input type="text" inputMode="numeric" autoComplete="one-time-code" required
              minLength={6} maxLength={6} pattern="[0-9]{6}" value={emailCode} onChange={event => setEmailCode(event.target.value)} /></label>
          </>}
        </>}
        <label>아이디<input name="username" autoComplete="username" autoCapitalize="none" spellCheck={false}
          required minLength={3} maxLength={32} pattern="[a-zA-Z0-9_.\-]+" title="영문·숫자·점·밑줄·하이픈, 3~32자" /></label>
        <label>비밀번호<input name="password" type="password" autoComplete={creating ? 'new-password' : 'current-password'}
          required minLength={8} maxLength={128} placeholder={creating ? '8자 이상' : undefined} /></label>
        {(recycler || carrier) && <div className="company-profile-fields">
          <h2>{carrier ? '운송 가능 조건' : '받을 수 있는 폐기물'}</h2>
          <div className="match-fields">
            <label>업체 소재지<input name="city" required maxLength={50} placeholder="예: 전주" /></label>
            <label>{carrier ? '월 최대 운송량 (톤)' : '월 최대 수용량 (톤)'}<input name="max_ton" type="number" required min="0.001" max="100000" step="any" defaultValue="5" /></label>
          </div>
          {recycler && <label>월 최소 반입량 (톤, 선택)<input name="min_ton" type="number" min="0.001" max="100000" step="any" placeholder="예: 1" /></label>}
          <label>{carrier ? '추가 운송 지역' : '추가 수거·반입 대상 지역'}<input name="regions" placeholder="예: 완주, 익산" maxLength={300} /></label>
          {recycler && <label>운반 방식<select name="transport">
            <option>업체 수거</option><option>배출업체 직접 운반</option>
          </select></label>}
          <div className="company-materials" role="group" aria-label="취급 재질">
            {materials.filter(material => material !== '플라스틱(미상)').map(material => (
              <label key={material}><input type="checkbox" name="material" value={material} />{material}</label>
            ))}
          </div>
        </div>}
        <button className="primary-button" type="submit" disabled={creating && !challenge}>
          {busy ? '처리 중…' : creating ? '계정 만들기' : '로그인'} <ArrowRight size={17} />
        </button>
      </fieldset>
    </form>
    {error && <p className="match-error" role="alert">{error}</p>}
    <div className="account-switch">
      <button type="button" className="subtle-button" disabled={busy || sendingCode} onClick={() => {
        setError('')
        setChallenge('')
        setEmailCode('')
        setCreating(!creating)
      }}>
        {creating ? '로그인으로 돌아가기' : '회원가입'}
      </button>
      {!creating && <>
        <button type="button" className="subtle-button" disabled={busy} onClick={() => onRecovery('username')}>아이디 찾기</button>
        <button type="button" className="subtle-button" disabled={busy} onClick={() => onRecovery('forgot')}>비밀번호 재설정</button>
      </>}
    </div>
  </>
}
