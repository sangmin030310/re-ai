import { useEffect, useRef } from 'react'
import { LogOut, X } from 'lucide-react'
import AccountRecovery from './AccountRecovery'
import { TrustForm } from './TrustSettings'
import type { CompanyRole, CompanySession } from './lib/api'
import './account-settings.css'

const roleLabels: Record<CompanyRole, string> = {
  supplier: '배출업체',
  recycler: '가공업체',
  carrier: '운송업체',
}

export default function AccountSettings({ company, onClose, onSignOut }: {
  company: CompanySession
  onClose: () => void
  onSignOut?: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => { dialog.current?.showModal() }, [])

  function close() { dialog.current?.close() }

  return <dialog ref={dialog} className="account-settings-dialog" aria-labelledby="account-settings-title" onClose={onClose}>
    <header className="account-settings-heading">
      <h2 id="account-settings-title">계정 설정</h2>
      <button type="button" className="icon-btn" aria-label="계정 설정 닫기" onClick={close}><X size={20} /></button>
    </header>
    <dl className="account-settings-company">
      <div><dt>업체명</dt><dd>{company.label}</dd></div>
      <div><dt>업체 유형</dt><dd>{roleLabels[company.role]}</dd></div>
    </dl>
    <TrustForm role={company.role} />
    <AccountRecovery mode="setup" signedIn onClose={close} embedded />
    {onSignOut && <footer className="account-settings-footer">
      <button type="button" className="subtle-button" onClick={() => { close(); onSignOut() }}><LogOut size={16} /> 로그아웃</button>
    </footer>}
  </dialog>
}
