// POST /chat istemcisi. Yanıt SSE akışıdır; olaylar docs/chat.md › Olay tipleri'ndedir:
// tool_call, source_chip, kpi_card, chart_card, selection_card, map_command, text_delta, citation,
// ardından done ya da error. EventSource POST desteklemediği için gövde fetch akışından okunup olaylar
// burada ayrıştırılır. Olay verisi olduğu gibi iletilir; yeniden hesaplanmaz.

export const NETWORK_MESSAGE = 'Sunucuya ulaşılamadı.'
export const STREAM_MESSAGE = 'Yanıt akışı beklenmedik şekilde kesildi.'
const REQUEST_MESSAGE = 'İstek iletilemedi.'

export interface SseEvent {
  event: string
  data: string
}

export interface ToolCall {
  id: string
  name: string
  input: Record<string, unknown>
}

export interface SourceChip {
  tool: string
  source: string
  as_of: string | null
  stale: boolean
  error_code: string | null
}

export interface KpiItem {
  field: string
  description: string
  value: number
}

export interface KpiCard {
  tool: string
  items: KpiItem[]
  source: string
  as_of: string | null
}

export const CHART_TYPES = ['bar_horizontal', 'bar_vertical', 'pie', 'line'] as const
export type ChartType = (typeof CHART_TYPES)[number]

export interface ChartItem {
  label: string
  value: number
}

// get_chart_data zarfı olduğu gibi (docs/chat.md › chart_card); noktaları sunucu hesaplar.
export interface ChartCard {
  tool: string
  chart_type: ChartType
  group_by: string
  metric: string
  date: string
  flights: number
  groups_total: number
  unclassified: number
  items: ChartItem[]
  filters: Record<string, unknown>
  source: string
  as_of: string | null
}

// Aday alanları resolve_flight_identity kontratındaki value_schema'dır; yalnızca
// flight_id ve matched_on zorunludur, diğerleri veride olmayabilir.
export type Candidate = Record<string, unknown> & { flight_id: string }

export interface SelectionCard {
  query: string
  message: string
  candidates: Candidate[]
  source: string
  as_of: string | null
}

// Cevaptaki bir parça etiketi (docs/chat.md › Atıf olayı). Eşleşmeyen etiket yalnızca
// kimlik taşır; eşleşende belge alanları search_documents zarfından olduğu gibi gelir.
export type Citation =
  | { chunk_id: string; dogrulandi: false }
  | {
      chunk_id: string
      dogrulandi: true
      title: string
      section: string
      revision: string
      effective_from: string
      status: string
    }

// Harita komutu: zarfın value'su olduğu gibi (docs/harita.md › map_command olayı).
export type ObjectType = 'flight' | 'stand'

export type MapCommand =
  | { command: 'focus_map_object'; object_type: ObjectType; id: string }
  | { command: 'highlight_map_set'; object_type: ObjectType; ids: string[] }

// Haritada seçili nesne; sonraki mesaja eklenir (docs/harita.md › Haritadan sohbete bağlam).
export interface SelectedObject {
  object_type: ObjectType
  id: string
}

export interface Done {
  status: string
  reason: string | null
  turns: number
  instruction: { name: string; version: string; summary: string }
  // Sorunun audit satırı; yazılamadıysa null ve geri bildirim gösterilmez (docs/audit.md).
  audit_id: string | null
}

export interface ChatHandlers {
  onToolCall: (call: ToolCall) => void
  onChip: (chip: SourceChip) => void
  onKpi: (card: KpiCard) => void
  onChart: (card: ChartCard) => void
  onSelection: (card: SelectionCard) => void
  onMapCommand: (command: MapCommand) => void
  onText: (text: string) => void
  onCitation: (citation: Citation) => void
  onDone: (done: Done) => void
  // Sunucunun genel Türkçe mesajı ya da istemcinin kendi genel mesajı.
  onError: (message: string) => void
}

// Tamamlanmış olayları döndürür; yarım kalan son parça rest'te bir sonraki okumayı bekler.
export function parseSse(buffer: string): { events: SseEvent[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, '\n')
  const blocks = normalized.split('\n\n')
  const rest = blocks.pop() ?? ''
  const events: SseEvent[] = []
  for (const block of blocks) {
    let event = 'message'
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
    }
    if (data.length > 0) events.push({ event, data: data.join('\n') })
  }
  return { events, rest }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseData(data: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(data)
    return isRecord(parsed) ? parsed : null
  } catch {
    return null
  }
}

function isString(value: unknown): value is string {
  return typeof value === 'string'
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

function isToolCall(data: Record<string, unknown>): data is Record<string, unknown> & ToolCall {
  return isString(data.id) && isString(data.name) && isRecord(data.input)
}

function isChip(data: Record<string, unknown>): data is Record<string, unknown> & SourceChip {
  return (
    isString(data.tool) &&
    isString(data.source) &&
    isNullableString(data.as_of) &&
    typeof data.stale === 'boolean' &&
    isNullableString(data.error_code)
  )
}

function isKpiItem(item: unknown): item is KpiItem {
  return (
    isRecord(item) &&
    isString(item.field) &&
    isString(item.description) &&
    typeof item.value === 'number'
  )
}

function isKpi(data: Record<string, unknown>): data is Record<string, unknown> & KpiCard {
  return (
    isString(data.tool) &&
    Array.isArray(data.items) &&
    data.items.every(isKpiItem) &&
    isString(data.source) &&
    isNullableString(data.as_of)
  )
}

function isChartItem(item: unknown): item is ChartItem {
  return isRecord(item) && isString(item.label) && typeof item.value === 'number'
}

function isChart(data: Record<string, unknown>): data is Record<string, unknown> & ChartCard {
  return (
    isString(data.tool) &&
    (CHART_TYPES as readonly string[]).includes(data.chart_type as string) &&
    isString(data.group_by) &&
    isString(data.metric) &&
    isString(data.date) &&
    typeof data.flights === 'number' &&
    typeof data.groups_total === 'number' &&
    typeof data.unclassified === 'number' &&
    Array.isArray(data.items) &&
    data.items.every(isChartItem) &&
    isRecord(data.filters) &&
    isString(data.source) &&
    isNullableString(data.as_of)
  )
}

function isCandidate(value: unknown): value is Candidate {
  return isRecord(value) && isString(value.flight_id)
}

function isSelection(
  data: Record<string, unknown>,
): data is Record<string, unknown> & SelectionCard {
  return (
    isString(data.query) &&
    isString(data.message) &&
    Array.isArray(data.candidates) &&
    data.candidates.every(isCandidate) &&
    isString(data.source) &&
    isNullableString(data.as_of)
  )
}

function isObjectType(value: unknown): value is ObjectType {
  return value === 'flight' || value === 'stand'
}

// Bilinen bir command, object_type ∈ {flight, stand}; focus için metin id, highlight için
// metin dizisi ids (docs/harita.md › Arayüz işleyicisi). Aksi halde olay yok sayılır.
function isMapCommand(data: Record<string, unknown>): data is Record<string, unknown> & MapCommand {
  if (!isObjectType(data.object_type)) return false
  if (data.command === 'focus_map_object') return isString(data.id)
  if (data.command === 'highlight_map_set') {
    return Array.isArray(data.ids) && data.ids.every(isString)
  }
  return false
}

// dogrulandi true ise beş belge alanının hepsi metin olmalı; false ise yalnızca kimlik gelir.
function isCitation(data: Record<string, unknown>): data is Record<string, unknown> & Citation {
  if (!isString(data.chunk_id)) return false
  if (data.dogrulandi === false) return true
  return (
    data.dogrulandi === true &&
    isString(data.title) &&
    isString(data.section) &&
    isString(data.revision) &&
    isString(data.effective_from) &&
    isString(data.status)
  )
}

function isDone(data: Record<string, unknown>): data is Record<string, unknown> & Done {
  const { instruction } = data
  return (
    isString(data.status) &&
    isNullableString(data.reason) &&
    typeof data.turns === 'number' &&
    isRecord(instruction) &&
    isString(instruction.name) &&
    isString(instruction.version) &&
    isString(instruction.summary) &&
    isNullableString(data.audit_id)
  )
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body = parseData(await response.text())
    if (body === null) return REQUEST_MESSAGE
    if (isString(body.detail)) return body.detail
    // 422'de detail bir listedir; yalnızca selected hakkındaki mesaj gösterilir
    // (ör. nesne veride yok). Diğer doğrulama mesajları genel mesaja düşer.
    if (Array.isArray(body.detail)) {
      for (const item of body.detail) {
        if (isRecord(item) && Array.isArray(item.loc) && item.loc.includes('selected')) {
          if (isString(item.msg)) return item.msg.replace(/^Value error, /, '')
        }
      }
    }
    return REQUEST_MESSAGE
  } catch {
    return REQUEST_MESSAGE
  }
}

// Olayları sırayla işler; akışı bitiren olay (done ya da error) geldiyse true döner.
// Biçimi bozuk ara olay atlanır; biçimi bozuk son olay akış hatası sayılır. Tablodaki
// dokuz tip dışındaki olay yok sayılır (docs/chat.md › Arayüz kuralları 1).
export function dispatch(event: SseEvent, handlers: ChatHandlers): boolean {
  const data = parseData(event.data)
  // GEÇİCİ: zarftan türetilen olayların verisini console'a yaz (sonra sil)
  if (['source_chip', 'kpi_card', 'selection_card', 'map_command'].includes(event.event)) console.log('[GEÇİCİ]', event.event, data) // GEÇİCİ
  switch (event.event) {
    case 'tool_call':
      if (data !== null && isToolCall(data)) handlers.onToolCall(data)
      return false
    case 'source_chip':
      if (data !== null && isChip(data)) handlers.onChip(data)
      return false
    case 'kpi_card':
      if (data !== null && isKpi(data)) handlers.onKpi(data)
      return false
    case 'chart_card':
      if (data !== null && isChart(data)) handlers.onChart(data)
      return false
    case 'selection_card':
      if (data !== null && isSelection(data)) handlers.onSelection(data)
      return false
    case 'map_command':
      if (data !== null && isMapCommand(data)) handlers.onMapCommand(data)
      return false
    case 'text_delta':
      if (data !== null && isString(data.text)) handlers.onText(data.text)
      return false
    case 'citation':
      if (data !== null && isCitation(data)) handlers.onCitation(data)
      return false
    case 'done':
      if (data !== null && isDone(data)) handlers.onDone(data)
      else handlers.onError(STREAM_MESSAGE)
      return true
    case 'error':
      handlers.onError(data !== null && isString(data.message) ? data.message : STREAM_MESSAGE)
      return true
    default:
      return false
  }
}

// Thumbs down: cevabı yanlış olarak işaretler (docs/audit.md › POST /feedback).
// Başarı yalnızca 204'tür; ağ hatası da dahil diğer her sonuç false döner.
export async function sendFeedback(auditId: string): Promise<boolean> {
  try {
    const response = await fetch('/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ audit_id: auditId }),
    })
    return response.status === 204
  } catch {
    return false
  }
}

export async function streamChat(
  message: string,
  handlers: ChatHandlers,
  selected: SelectedObject | null = null,
): Promise<void> {
  let response: Response
  try {
    response = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // Seçim yoksa selected alanı hiç gönderilmez (açık null 422 verir).
      body: JSON.stringify(selected === null ? { message } : { message, selected }),
    })
  } catch {
    handlers.onError(NETWORK_MESSAGE)
    return
  }

  if (!response.ok || response.body === null) {
    handlers.onError(await errorDetail(response))
    return
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      const parsed = parseSse(buffer + value)
      buffer = parsed.rest
      for (const event of parsed.events) {
        if (dispatch(event, handlers)) return
      }
    }
  } catch {
    handlers.onError(STREAM_MESSAGE)
    return
  }
  // Akış done ya da error olmadan bitti.
  handlers.onError(STREAM_MESSAGE)
}
