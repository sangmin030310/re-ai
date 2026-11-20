export interface Project {
  id: string
  title: string
  organization_id: string
  profile: Record<string, unknown>
  selected_route: string | null
  created_at: string
  updated_at: string
}
export interface Message {
  id: string
  project_id: string
  role: 'user' | 'assistant'
  content: string
  actions: { id: string; label: string; value: string | null }[]
  created_at: string
}
export interface DocumentInfo {
  id: string
  project_id: string
  name: string
  mime: string
  size: number | null
  created_at: string
  source?: 'upload' | 'request'
  project_title?: string
}
export interface RouteOption {
  id: string
  title: string
  tag: string
  detail: string
  checks: string[]
}
export interface Analysis {
  stage: string
  missing_fields: string[]
  profile: { material?: string; monthly_ton?: number; contamination?: string }
  routes: RouteOption[]
  selected_route: string | null
  verified: boolean
  disclaimer: string
  steps: { label: string; state: 'done' | 'current' | 'waiting' }[]
}
interface MessageResponse {
  messages: Message[]
  project: Project
  analysis: Analysis
  agent_reply: { status: string; agent: string }
  document_command?: { changed: boolean; open_archive?: boolean; saved_request?: IntakeRequest }
}

export const legalStatuses = ['확인 전', '폐기물', '순환자원 인정', '부산물'] as const
export const frequencies = ['매월 정기', '주기 협의', '1회성'] as const
export const pricePreferences = ['협의', '매각 희망', '처리비 지급 가능'] as const
export interface IntakeRequest {
  material: string
  monthly_ton: number
  region: string
  contamination: string
  packaging: string
  notes: string
  legal_status?: typeof legalStatuses[number]
  waste_code?: string
  frequency?: typeof frequencies[number]
  address?: string
  price_preference?: typeof pricePreferences[number]
  attachment_ids?: string[]
}
export interface Evidence { title: string; detail: string; source: string; checked_at: string | null }
export interface AgentAssessment {
  source: string
  score: number | null
  summary: string
  reasons: string[]
  warnings: string[]
  evidence: Evidence[]
}
export interface RequestAssessment {
  source: string
  legal_status: string | null
  summary: string
  evidence: Evidence[]
  warnings: string[]
  unverified: string[]
  missing_fields: string[]
}
export interface Trust {
  permit_type: string | null
  permit_number: string | null
  permit_valid_until: string | null
  price_model: string | null
  permit_registered: boolean
  permit_verified: boolean
  permit_expired: boolean
  verified_at: string | null
  verify_note: string | null
  stats: { completed_deals: number; inquiries_received: number; reply_rate: number | null }
}
export interface TrustDetails {
  business_number: string
  address: string
  permit_type: string
  permit_number: string
  permit_valid_until: string | null
  price_model: string
}
export type PriceType = '매입' | '처리비' | '무상'
export type Quote = { price_type: PriceType | '협의' | null; unit_price: number | null; available_from: string | null }
export const materials = ['PP', 'PE', 'PET', '철/금속', '혼합 플라스틱', '플라스틱(미상)', '폐지', '슬러지', '기타']
export type CompanyRole = 'supplier' | 'recycler' | 'carrier'
export interface CompanySession {
  id: string
  label: string
  role: CompanyRole
  company_name?: string
  operator?: boolean
}
type Credentials = { username: string; password: string }
type CompanyProfile = { city: string; regions: string[]; materials: string[]; max_ton: number }
type Registration = Credentials & {
  company_name: string; role: CompanyRole;
  recovery_email: string
  signup_email_challenge: string
  signup_email_code: string
  recycler_profile?: CompanyProfile & { transport: string; min_ton?: number }
  carrier_profile?: CompanyProfile
}
export interface Company {
  id: string
  name: string
  city: string
  materials: string[]
  regions: string[]
  max_ton: number
  min_ton?: number | null
  transport: string
  route: string
  intro: string
  check: string
  inquiry_available: boolean
  registered: boolean
  match?: { matched: string[]; unmet: string[] }
  distance_km?: number | null
  trust?: Trust
  agent?: AgentAssessment | null
}
export type InquiryReviewStatus = 'accepted' | 'needs_info' | 'declined'
export type InquiryReview = { status: InquiryReviewStatus; reason: string; updated_at: string; quote?: Quote | null }
interface Inquiry {
  id: string
  project_id: string
  sender_id: string
  initiated_by: string
  sender_name: string
  recipient_name: string
  recipient_id: string
  recipient_role: 'recycler' | 'carrier'
  can_plan_transport: boolean
  transport_to: string | null
  review: InquiryReview | null
  created_at: string
  deal_id: string | null
  deal_status: DealStatus | null
  can_start_deal: boolean
  demand_id?: string | null
  recipient_trust?: Trust
}
export interface TransportOptions { companies: Company[]; request: IntakeRequest; destination: string }
export type SupplyCriteria = Partial<Pick<IntakeRequest, 'material' | 'monthly_ton' | 'region'>>
export type SupplyListing = Omit<IntakeRequest, 'notes' | 'address' | 'attachment_ids'> & {
  id: string; name: string; inquiry_id: string | null; attachment_count?: number; trust?: Trust
}
export interface SupplyResults { criteria: SupplyCriteria; results: SupplyListing[] }
export interface InquirySummary extends Inquiry {
  material: string
  last_message: string
  last_at: string
}
export interface InquiryDetail extends Inquiry {
  request: IntakeRequest
  attachments: { id: string; name: string; size: number }[]
  messages: { sequence: number; author_id: string; content: string; created_at: string }[]
}

export interface ResponseRow {
  inquiry_id: string
  company_id: string
  company_name: string
  city: string | null
  distance_km: number | null
  trust: Trust
  review: { status: InquiryReviewStatus; reason: string; updated_at: string } | null
  quote: Quote | null
  replied_at: string | null
  sent_at: string
  deal_id: string | null
  deal_status: DealStatus | null
}
export interface BatchResult {
  created: { recipient_id: string; id: string; name: string }[]
  skipped: { recipient_id: string; id: string | null; reason: string }[]
}

export type DealStatus = 'negotiating' | 'agreed' | 'transport_pending' | 'scheduled' | 'picked_up' | 'delivered' | 'completed' | 'cancelled'
export type DealRole = 'supplier' | 'recycler' | 'carrier' | 'carrier_candidate'
export type TransportBy = 'supplier' | 'recycler' | 'supplier_self' | 'recycler_self'
export interface DealTerms {
  price_type: PriceType
  unit_price: number | null
  quantity_ton: number
  frequency: typeof frequencies[number]
  start_date: string | null
  transport_by: TransportBy
  notes?: string
}
export interface Shipment {
  pickup_address?: string | null
  pickup_window?: string | null
  pickup_equipment?: string | null
  packaging?: string | null
  planned_ton?: number | null
  dropoff_address?: string | null
  dropoff_window?: string | null
  unloading?: string | null
  vehicle?: string | null
  driver_contact?: string | null
  notes?: string | null
  picked_up_ton?: number
  delivered_ton?: number
}
export interface ChecklistItem {
  key: string
  label: string
  owner: 'supplier' | 'recycler' | 'carrier' | 'any'
  stage: 'before_agreement' | 'before_transport' | 'after_delivery'
  note: string
  source: string
  state: 'pending' | 'done' | 'not_applicable'
  state_note: string
  updated_by: string | null
  updated_at: string | null
  files: { id: string; name: string; size: number; created_at: string; uploader_name: string }[]
}
export interface TransportQuoteRow {
  id: string
  carrier_id: string
  carrier_name: string
  status: 'requested' | 'quoted' | 'declined' | 'selected' | 'not_selected'
  note: string
  quote: { price: number; available_date: string; vehicle: string; note: string } | null
  trust: Trust
  updated_at: string
}
export interface DealParty { id: string; name: string; trust: Trust }
export interface NextAction { label: string; mine: boolean }
export interface DealSummary {
  id: string
  status: DealStatus
  status_label: string
  my_role: DealRole
  supplier_name: string
  recycler_name: string
  carrier_name: string | null
  material: string
  quantity_ton: number
  route: string
  next_action: NextAction
  updated_at: string
}
export interface Deal {
  id: string
  project_id: string | null
  source_inquiry_id: string | null
  status: DealStatus
  status_label: string
  flow: { status: DealStatus; label: string }[]
  my_role: DealRole
  parties: { supplier: DealParty; recycler: DealParty; carrier: DealParty | null }
  request: Partial<IntakeRequest>
  request_files: { id: string; name: string; size: number }[]
  destination_city: string | null
  distance_km: number | null
  terms: Partial<DealTerms> | null
  terms_by: string | null
  terms_agreed_at: string | null
  terms_proposed_by_me: boolean
  suggested_terms: Partial<DealTerms> | null
  transport_owner: 'supplier' | 'recycler' | null
  needs_carrier: boolean
  shipment: Shipment
  transport_requests: TransportQuoteRow[]
  checklist: ChecklistItem[]
  events: { sequence: number; actor_id: string; actor_name: string; kind: string; detail: string; created_at: string }[]
  messages: { sequence: number; author_id: string; author_name: string; content: string; created_at: string }[]
  can_chat: boolean
  next_action: NextAction
  cancel_reason: string | null
  created_at: string
  updated_at: string
  labels: { transport: Record<TransportBy, string>; price: Record<PriceType, string> }
}
export interface CarrierCandidate {
  id: string; name: string; city: string; regions: string[]; max_ton: number
  distance_km: number | null; trust: Trust; requested: boolean
}
export interface DemandPostInput {
  material: string
  monthly_ton: number
  regions: string[]
  price_type: PriceType | '협의'
  unit_price: number | null
  conditions: string
  until: string | null
}
export interface DemandPost extends DemandPostInput {
  id: string
  recycler_id: string
  recycler_name: string
  city: string | null
  status: 'open' | 'closed'
  expired: boolean
  distance_km: number | null
  trust: Trust
  my_inquiry_id: string | null
  response_count: number | null
  created_at: string
  updated_at: string
}
export interface OperatorCompany { id: string; name: string; role: CompanyRole; details: Partial<TrustDetails>; trust: Trust }

async function fetchApi(path: string, options?: RequestInit): Promise<Response> {
  let response: Response
  try {
    const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
    const headers = new Headers(options?.headers)
    const invite = sessionStorage.getItem('reai_invite')
    if (invite) headers.set('Authorization', `Bearer ${invite}`)
    response = await fetch(`${base}/api${path}`, { ...options, headers })
  } catch {
    throw new Error('서버 연결에 실패했습니다. FastAPI 서버가 실행 중인지 확인해주세요.')
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({})) as { detail?: unknown }
    throw new Error(typeof data.detail === 'string' ? data.detail : `요청 실패 (HTTP ${response.status})`)
  }
  return response
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  return (await fetchApi(path, options)).json() as Promise<T>
}

async function download(path: string, filename: string) {
  const url = URL.createObjectURL(await (await fetchApi(path)).blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 3000)
}

const json = (body: unknown) => ({ headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const requestName = '폐기물 인수 검토 요청서.docx'

export const api = {
  session: () => request<CompanySession>('/session'),
  sendSignupEmailCode: (email: string) => request<{ challenge_id: string }>(
    '/accounts/recovery/signup-code', { method: 'POST', ...json({ email }) }),
  register: (data: Registration) => request<CompanySession>('/accounts/register', { method: 'POST', ...json(data) }),
  login: (data: Credentials) => request<CompanySession>('/accounts/login', { method: 'POST', ...json(data) }),
  logout: () => request<{ ok: boolean }>('/accounts/logout', { method: 'POST' }),
  recoveryEmail: () => request<{ email: string | null; pending_email: string | null; mail_available: boolean }>('/accounts/recovery/email'),
  setRecoveryEmail: (email: string, password: string) =>
    request<{ ok: boolean; mail_sent: boolean; message?: string }>('/accounts/recovery/email', { method: 'POST', ...json({ email, password }) }),
  sendPendingEmail: () => request<{ ok: boolean }>('/accounts/recovery/email/resend', { method: 'POST' }),
  requestRecovery: (email: string, purpose: 'username' | 'reset') =>
    request<{ ok: boolean }>('/accounts/recovery/request', { method: 'POST', ...json({ email, purpose }) }),
  verifyRecoveryEmail: (token: string) =>
    request<{ ok: boolean }>('/accounts/recovery/verify', { method: 'POST', ...json({ token }) }),
  resetPassword: (token: string, password: string) =>
    request<{ ok: boolean }>('/accounts/recovery/reset', { method: 'POST', ...json({ token, password }) }),
  health: () => request<{
    ok: boolean; mode: 'mock' | 'openai' | 'chatgpt'; demo_workspaces: boolean; online_demo?: boolean; pc_share?: boolean; account_login?: boolean;
    workspaces?: { id: string; label: string }[]
  }>('/health'),
  chatGPTStatus: () => request<{ active: string | null; enabled: boolean; email: string | null; model: string | null; accounts: { id: string; email: string }[] }>('/chatgpt'),
  connectChatGPT: (client_id?: string) => request<{ url: string }>('/chatgpt/connect', { method: 'POST', ...json({ client_id }) }),
  chatGPTModels: () => request<{ slug: string; name: string }[]>('/chatgpt/models'),
  selectChatGPTModel: (model: string) => request<{ ok: boolean }>('/chatgpt/model', { method: 'POST', ...json({ model }) }),
  disconnectChatGPT: () => request<{ revoked: boolean }>('/chatgpt/disconnect', { method: 'POST' }),
  intakeRequest: (project: string) => request<{ request: IntakeRequest | null; selected_company_id: string | null; inquiries: Record<string, string>; listing: IntakeRequest | null }>(`/matching/requests/${project}`),
  saveIntake: (project: string, data: IntakeRequest) => request<IntakeRequest>(`/matching/requests/${project}`, { method: 'PUT', ...json(data) }),
  publishSupply: (project: string, available_ton: number) => request<IntakeRequest>(`/matching/requests/${project}/listing`, { method: 'PUT', ...json({ available_ton }) }),
  unpublishSupply: (project: string) => request<{ ok: boolean }>(`/matching/requests/${project}/listing`, { method: 'DELETE' }),
  searchSupplies: (criteria: SupplyCriteria, message = '') => request<SupplyResults>('/matching/supplies/search', { method: 'POST', ...json({ ...criteria, message }) }),
  contactSupply: (id: string, content: string) => request<{ id: string }>(`/matching/supplies/${id}/contact`, { method: 'POST', ...json({ content }) }),
  companies: (project: string) => request<Company[]>(`/matching/requests/${project}/companies?include_excluded=true`),
  transportOptions: (project: string, destination: string) => request<TransportOptions>(
    `/matching/requests/${project}/transport?destination_inquiry_id=${encodeURIComponent(destination)}`,
  ),
  selectCompany: (project: string, company_id: string, data: IntakeRequest) =>
    request<{ selected_company_id: string }>(`/matching/requests/${project}/selection`, {
      method: 'PUT', ...json({ company_id, request: data }),
    }),
  downloadIntake: (project: string) => download(`/matching/requests/${project}/download`, requestName),
  sendInquiry: (project_id: string, recipient_id: string, content: string, data: IntakeRequest, destination_inquiry_id?: string) =>
    request<{ id: string }>('/matching/inquiries', { method: 'POST', ...json({ project_id, recipient_id, content, request: data, destination_inquiry_id }) }),
  inquiries: () => request<InquirySummary[]>('/matching/inquiries'),
  inquiry: (id: string) => request<InquiryDetail>(`/matching/inquiries/${id}`),
  saveInquiryReview: (id: string, status: InquiryReviewStatus, reason: string) =>
    request<InquiryReview>(`/matching/inquiries/${id}/review`, { method: 'PUT', ...json({ status, reason }) }),
  reply: (id: string, content: string, client_id: string) =>
    request<{ ok: boolean }>(`/matching/inquiries/${id}/messages`, { method: 'POST', ...json({ content, client_id }) }),
  downloadAttachment: (id: string) => download(`/matching/inquiries/${id}/attachment`, requestName),
  projects: () => request<Project[]>('/projects'),
  createProject: (title = '새 폐기물 검토') => request<Project>('/projects', { method: 'POST', ...json({ title }) }),
  renameProject: (id: string, title: string) => request<Project>(`/projects/${id}`, { method: 'PATCH', ...json({ title }) }),
  deleteProject: (id: string) => request<{ ok: boolean }>(`/projects/${id}`, { method: 'DELETE' }),
  messages: (id: string) => request<Message[]>(`/projects/${id}/messages`),
  analysis: (id: string) => request<Analysis>(`/projects/${id}/analysis`),
  send: (id: string, content: string, intake = false, requestDraft?: IntakeRequest, documentSelection?: string) =>
    request<MessageResponse>(`/projects/${id}/messages`, {
      method: 'POST', ...json({ content, intake, request_draft: requestDraft, document_selection: documentSelection }),
    }),
  selectRoute: (id: string, route_id: string) => request<{ project: Project; analysis: Analysis; notice: string }>(`/projects/${id}/select-route`, { method: 'POST', ...json({ route_id }) }),
  documents: (id?: string) => request<DocumentInfo[]>(`/documents${id ? `?project_id=${encodeURIComponent(id)}` : ''}`),
  upload: async (id: string, file: File) => {
    const data = new FormData()
    data.append('file', file)
    return request<DocumentInfo>(`/projects/${id}/documents`, { method: 'POST', body: data })
  },
  downloadDocument: (id: string, filename: string) => download(`/documents/${id}/download`, filename),
  deleteDocument: (id: string) => request<{ ok: boolean }>(`/documents/${id}`, { method: 'DELETE' }),
  exportProject: (id: string) => request<Record<string, unknown>>(`/projects/${id}/export`),

  // 매칭 확장: 에이전트 검토, 일괄 문의, 답변 비교, 첨부 파일
  requestReview: (project: string) => request<RequestAssessment>(`/matching/requests/${project}/review`),
  responses: (project: string) => request<ResponseRow[]>(`/matching/requests/${project}/responses`),
  sendBatch: (project_id: string, recipient_ids: string[], content: string, data: IntakeRequest) =>
    request<BatchResult>('/matching/inquiries/batch', { method: 'POST', ...json({ project_id, recipient_ids, content, request: data }) }),
  saveQuoteReview: (id: string, status: InquiryReviewStatus, reason: string, quote: Partial<Quote>) =>
    request<InquiryReview>(`/matching/inquiries/${id}/review`, { method: 'PUT', ...json({ status, reason, ...quote }) }),
  downloadInquiryFile: (inquiry: string, file: { id: string; name: string }) =>
    download(`/matching/inquiries/${inquiry}/files/${file.id}`, file.name),

  // 거래 건
  deals: () => request<DealSummary[]>('/deals'),
  deal: (id: string) => request<Deal>(`/deals/${id}`),
  createDeal: (inquiry_id: string) => request<Deal>('/deals', { method: 'POST', ...json({ inquiry_id }) }),
  proposeTerms: (id: string, terms: DealTerms) => request<Deal>(`/deals/${id}/terms`, { method: 'PUT', ...json(terms) }),
  acceptTerms: (id: string) => request<Deal>(`/deals/${id}/terms/accept`, { method: 'POST' }),
  carriers: (id: string) => request<CarrierCandidate[]>(`/deals/${id}/carriers`),
  requestTransport: (id: string, carrier_ids: string[], note: string) =>
    request<Deal>(`/deals/${id}/transport-requests`, { method: 'POST', ...json({ carrier_ids, note }) }),
  respondTransport: (id: string, body: { action: 'quote' | 'decline'; price?: number; available_date?: string; vehicle?: string; note?: string }) =>
    request<Deal>(`/deals/${id}/transport-requests/mine`, { method: 'PUT', ...json(body) }),
  selectTransport: (id: string, requestId: string) => request<Deal>(`/deals/${id}/transport-requests/${requestId}/select`, { method: 'POST' }),
  updateShipment: (id: string, shipment: Shipment) => request<Deal>(`/deals/${id}/shipment`, { method: 'PUT', ...json(shipment) }),
  progress: (id: string, step: 'scheduled' | 'picked_up' | 'delivered' | 'completed', actual_ton?: number, note = '') =>
    request<Deal>(`/deals/${id}/progress`, { method: 'POST', ...json({ step, actual_ton, note }) }),
  cancelDeal: (id: string, reason: string) => request<Deal>(`/deals/${id}/cancel`, { method: 'POST', ...json({ reason }) }),
  updateChecklist: (id: string, key: string, state: ChecklistItem['state'], note = '') =>
    request<Deal>(`/deals/${id}/checklist/${encodeURIComponent(key)}`, { method: 'PUT', ...json({ state, note }) }),
  uploadDealFile: (id: string, key: string, file: File) => {
    const data = new FormData()
    data.append('key', key)
    data.append('file', file)
    return request<Deal>(`/deals/${id}/files`, { method: 'POST', body: data })
  },
  downloadDealFile: (id: string, file: { id: string; name: string }) => download(`/deals/${id}/files/${file.id}`, file.name),
  downloadDealRequestFile: (id: string, file: { id: string; name: string }) => download(`/deals/${id}/request-files/${file.id}`, file.name),
  dealMessage: (id: string, content: string, client_id: string) =>
    request<{ ok: boolean }>(`/deals/${id}/messages`, { method: 'POST', ...json({ content, client_id }) }),

  // 수요 공고
  myDemands: () => request<DemandPost[]>('/matching/demands?mine=true'),
  demands: (project_id?: string) => request<DemandPost[]>(`/matching/demands${project_id ? `?project_id=${encodeURIComponent(project_id)}` : ''}`),
  createDemand: (data: DemandPostInput) => request<DemandPost>('/matching/demands', { method: 'POST', ...json(data) }),
  updateDemand: (id: string, data: DemandPostInput) => request<DemandPost>(`/matching/demands/${id}`, { method: 'PUT', ...json(data) }),
  closeDemand: (id: string) => request<DemandPost>(`/matching/demands/${id}`, { method: 'DELETE' }),
  replyDemand: (id: string, project_id: string, content: string) =>
    request<{ id: string }>(`/matching/demands/${id}/reply`, { method: 'POST', ...json({ project_id, content }) }),

  // 신뢰 정보
  myTrust: () => request<{ details: TrustDetails; trust: Trust; permit_types: string[]; operator: boolean }>('/accounts/trust'),
  saveTrust: (details: TrustDetails) => request<{ details: TrustDetails; trust: Trust }>('/accounts/trust', { method: 'PUT', ...json(details) }),
  operatorCompanies: () => request<OperatorCompany[]>('/operator/companies'),
  verifyCompany: (id: string, verified: boolean, note: string) =>
    request<Trust>(`/operator/companies/${id}/verification`, { method: 'PUT', ...json({ verified, note }) }),
}

export function newClientId() {
  return crypto.randomUUID?.() ?? '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, digit => (
    Number(digit) ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (Number(digit) / 4)))
  ).toString(16))
}
