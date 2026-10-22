// POST /chat istemcisi. Yanıt SSE akışıdır; olaylar docs/chat.md › Olay tipleri'ndedir:
// tool_call, source_chip, kpi_card, selection_card, text_delta, ardından done ya da
// error. EventSource POST desteklemediği için gövde fetch akışından okunup olaylar
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

export interface Done {
  status: string
  reason: string | null
  turns: number
  instruction: { name: string; version: string; summary: string }
}

export interface ChatHandlers {
  onToolCall: (call: ToolCall) => void
  onChip: (chip: SourceChip) => void
  onKpi: (card: KpiCard) => void
  onSelection: (card: SelectionCard) => void
  onText: (text: string) => void
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

function isDone(data: Record<string, unknown>): data is Record<string, unknown> & Done {
  const { instruction } = data
  return (
    isString(data.status) &&
    isNullableString(data.reason) &&
    typeof data.turns === 'number' &&
    isRecord(instruction) &&
    isString(instruction.name) &&
    isString(instruction.version) &&
    isString(instruction.summary)
  )
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body = parseData(await response.text())
    // 422'de FastAPI detail'i bir liste olarak döner; yalnızca metin olanı gösterilir.
    return body !== null && isString(body.detail) ? body.detail : REQUEST_MESSAGE
  } catch {
    return REQUEST_MESSAGE
  }
}

// Olayları sırayla işler; akışı bitiren olay (done ya da error) geldiyse true döner.
// Biçimi bozuk ara olay atlanır; biçimi bozuk son olay akış hatası sayılır. Tablodaki
// yedi tip dışındaki olay yok sayılır (docs/chat.md › Arayüz kuralları 1).
export function dispatch(event: SseEvent, handlers: ChatHandlers): boolean {
  const data = parseData(event.data)
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
    case 'selection_card':
      if (data !== null && isSelection(data)) handlers.onSelection(data)
      return false
    case 'text_delta':
      if (data !== null && isString(data.text)) handlers.onText(data.text)
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

export async function streamChat(message: string, handlers: ChatHandlers): Promise<void> {
  let response: Response
  try {
    response = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
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
