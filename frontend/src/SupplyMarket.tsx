import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowRight, ArrowUp, Building2, Inbox, Leaf } from 'lucide-react'
import { api, materials, type SupplyCriteria, type SupplyListing } from './lib/api'

const initialReply = '어떤 재질이 얼마나 필요하세요? 예를 들어 “PP 0.8톤이 필요해요. 전주 근처에 있나요?”라고 물어보세요.'

export default function SupplyMarket({ visible, preset, onInquiry, onOpenConversations }: {
  visible: boolean
  preset?: SupplyCriteria
  onInquiry: (id: string) => void
  onOpenConversations: () => void
}) {
  const [criteria, setCriteria] = useState<SupplyCriteria>({})
  const [results, setResults] = useState<SupplyListing[]>([])
  const [conversation, setConversation] = useState<{ role: 'user' | 'assistant'; text: string }[]>([])
  const [question, setQuestion] = useState('')
  const [target, setTarget] = useState<SupplyListing | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const composer = useRef<HTMLFormElement>(null)
  const lastMessage = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let ignore = false
    setLoading(true)
    setError('')
    setTarget(null)
    api.searchSupplies(preset ?? {}).then(result => {
      if (ignore) return
      setCriteria(result.criteria)
      setResults(result.results)
    })
      .catch(failure => { if (!ignore) setError((failure as Error).message) })
      .finally(() => { if (!ignore) setLoading(false) })
    return () => { ignore = true }
  }, [preset])

  useEffect(() => {
    if (conversation.length) lastMessage.current?.scrollIntoView({ block: 'nearest' })
  }, [conversation])

  useEffect(() => { if (target) composer.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }, [target])

  async function search(filters: SupplyCriteria, prompt = '') {
    setBusy(true)
    setError('')
    setTarget(null)
    if (prompt) {
      setQuestion('')
      setConversation(previous => [...previous, { role: 'user', text: prompt }])
    }
    try {
      const { criteria: next, results: found } = await api.searchSupplies(filters, prompt)
      setCriteria(next)
      setResults(found)
      if (prompt) {
        const amount = next.monthly_ton ?? 0
        let answer = '필요한 재질과 물량을 알려주시면 공개된 물량과 비교할게요.'
        if (next.material && amount) {
          const scope = next.region ? `${next.region}에서` : '공개 물량에서'
          const first = found[0]
          if (!first) answer = `${scope} 공개된 ${next.material} 물량을 찾지 못했어요. 지역을 바꿔 찾아볼 수 있어요.`
          else if (first.monthly_ton >= amount) answer = `${scope} ${next.material} ${amount}톤을 채울 수 있는 후보를 찾았어요. 물량이 가장 가까운 곳은 ${first.name}(${first.monthly_ton}톤)입니다. 가격과 인도 조건은 업체에 문의해 주세요.`
          else answer = `${scope} ${next.material} ${amount}톤을 한 곳에서 채우기는 어려워요. 가장 많은 곳은 ${first.name}(${first.monthly_ton}톤)입니다. 아래에서 나눠 받을 곳을 검토할 수 있어요.`
        } else if (next.material) {
          answer = `${next.material} 공개 물량 ${found.length}건을 찾았어요. 몇 톤이 필요한지 알려주시면 물량이 맞는 곳부터 보여드릴게요.`
        } else if (amount) {
          answer = `${amount}톤이 필요하시군요. PP, PE, PET처럼 필요한 재질을 알려주세요.`
        } else if (next.region) {
          answer = `${next.region}의 공개 물량 ${found.length}건을 찾았어요. 필요한 재질과 물량을 알려주시면 조건에 맞춰 찾아볼게요.`
        }
        setConversation(previous => [...previous, { role: 'assistant', text: answer }])
      }
    } catch (failure) {
      if (prompt) setQuestion(prompt)
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function send(event: FormEvent) {
    event.preventDefault()
    if (!target || busy || !message.trim()) return
    setBusy(true)
    setError('')
    try {
      const { id } = await api.contactSupply(target.id, message.trim())
      onInquiry(id)
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function contact(item: SupplyListing) {
    if (item.inquiry_id) { onInquiry(item.inquiry_id); return }
    const amount = Math.min(criteria.monthly_ton ?? item.monthly_ton, item.monthly_ton)
    setMessage(`안녕하세요. 공개하신 ${item.material} 중 ${amount}톤을 받고 싶습니다. 공급 가능한 시기와 가격, 인도 조건을 알려주실 수 있을까요?`)
    setTarget(item)
  }

  if (!visible) return null

  return <>
    <header className="chat-heading supply-heading">
      <div>
        <h1>공급처 찾기</h1>
        <div className="heading-sub">배출업체가 공개한 물량을 비교하고 필요한 곳에 문의하세요.</div>
      </div>
      <button className="subtle-button" type="button" onClick={onOpenConversations}><Inbox size={16} /> 업체 대화 보기</button>
    </header>
    <div className="chat-scroller">
      <div className="messages supply-chat" aria-label="공급처 검색 대화" aria-live="polite">
        {[{ role: 'assistant', text: initialReply }, ...conversation].map((message, index) => (
          <div className={`message-row ${message.role}`} key={index}>
            {message.role === 'assistant' && <div className="assistant-avatar"><Leaf size={17} /></div>}
            <div className="message-column">
              {message.role === 'assistant' && <div className="message-author">Re AI <span>공급처 검색</span></div>}
              <div className="message-bubble">{message.text}</div>
            </div>
          </div>
        ))}
        <div ref={lastMessage} />
      </div>
      <div className="supply-market">
      <details className="match-card supply-filters">
        <summary>검색 조건 직접 입력</summary>
        <form className="match-form" onSubmit={event => {
          event.preventDefault()
          const form = new FormData(event.currentTarget)
          const material = String(form.get('material'))
          const region = String(form.get('region')).trim()
          const amount = Number(form.get('amount'))
          if (!busy) void search({ material: material || undefined, region: region || undefined, monthly_ton: amount || undefined })
        }}>
          <fieldset key={JSON.stringify(criteria)} disabled={busy || loading}>
            <div className="match-fields">
              <label>재질<select name="material" defaultValue={criteria.material ?? ''}>
                <option value="">전체 재질</option>{materials.map(material => <option key={material}>{material}</option>)}
              </select></label>
              <label>필요 물량 (톤)<input name="amount" type="number" min="0.001" step="any" max="100000" defaultValue={criteria.monthly_ton ?? ''} /></label>
            </div>
            <label>배출 지역<input name="region" maxLength={50} placeholder="예: 전주" defaultValue={criteria.region ?? ''} /></label>
            <button className="subtle-button" type="submit">조건 적용</button>
          </fieldset>
        </form>
      </details>
      {error && <p className="match-error" role="alert">{error}</p>}
      <div className="market-results"><h2>공개 물량 {results.length}건</h2>{criteria.monthly_ton && <span>요청한 물량을 채울 수 있는 곳부터 표시</span>}</div>
      {loading ? <p className="match-muted" role="status">공개 물량을 불러오는 중…</p> :
        !results.length ? <p className="market-empty">조건에 맞는 공개 물량이 없습니다.</p> :
          <div className="market-list">{results.map(item => <button className="market-item" key={item.id} disabled={busy}
            onClick={() => contact(item)}>
            <span className="market-symbol"><Building2 size={22} /></span>
            <span className="market-item-info">
              <strong className="market-item-name">{item.name}</strong>
              <span className="market-item-description">{item.region} · {item.material} · 공개 물량 {item.monthly_ton}톤</span>
              <span className="market-item-description">오염 상태 · {item.contamination} / 포장 상태 · {item.packaging}</span>
              <span className="market-tags"><span>{item.inquiry_id ? '문의 열기' : '공급 문의'}</span></span>
            </span>
            <ArrowRight size={18} />
          </button>)}</div>}
      {target && <form className="match-card match-form" ref={composer} onSubmit={send}>
        <div className="match-card-head"><h2>{target.name}에 공급 문의</h2>
          <button className="subtle-button" type="button" disabled={busy} onClick={() => setTarget(null)}>닫기</button>
        </div>
        <label>문의 메시지<textarea rows={3} required maxLength={2000} disabled={busy} value={message} onChange={event => setMessage(event.target.value)} /></label>
        {error && <p className="match-error" role="alert">{error}</p>}
        <button className="primary-button" type="submit" disabled={busy || !message.trim()}>공급 문의 보내기 <ArrowRight size={16} /></button>
      </form>}
      </div>
    </div>
    <div className="composer-wrap">
      <form className="composer" onSubmit={event => { event.preventDefault(); if (question.trim() && !busy) void search(criteria, question.trim()) }}>
        <textarea aria-label="공급처 질문" rows={2} maxLength={1000} value={question} disabled={busy || loading}
          onChange={event => setQuestion(event.target.value)} onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault()
              event.currentTarget.form?.requestSubmit()
            }
          }} placeholder="PP 0.8톤이 필요한데 전주 근처에서 구할 수 있나요?" />
        <div className="composer-footer">
          <div className="composer-tools"><span className="composer-hint">Enter 전송 · Shift+Enter 줄바꿈</span></div>
          <button className="send-btn" type="submit" aria-label="공급처 질문 전송" disabled={busy || loading || !question.trim()}><ArrowUp size={19} /></button>
        </div>
      </form>
    </div>
  </>
}
