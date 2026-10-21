// POST /chat istemcisi. Yanıt SSE akışıdır (backend/main.py): delta {"text"} olayları,
// ardından done {"stop_reason"} ya da error {"message"}. EventSource POST desteklemediği
// için gövde fetch akışından okunup olaylar burada ayrıştırılır.

export const NETWORK_MESSAGE = 'Sunucuya ulaşılamadı.'
export const STREAM_MESSAGE = 'Yanıt akışı beklenmedik şekilde kesildi.'
const REQUEST_MESSAGE = 'İstek iletilemedi.'

export interface SseEvent {
  event: string
  data: string
}

export interface ChatHandlers {
  onDelta: (text: string) => void
  onDone: (stopReason: string | null) => void
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

function field(data: string, name: string): unknown {
  try {
    const parsed: unknown = JSON.parse(data)
    return typeof parsed === 'object' && parsed !== null && name in parsed
      ? (parsed as Record<string, unknown>)[name]
      : undefined
  } catch {
    return undefined
  }
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const detail = field(await response.text(), 'detail')
    // 422'de FastAPI detail'i bir liste olarak döner; yalnızca metin olanı gösterilir.
    return typeof detail === 'string' ? detail : REQUEST_MESSAGE
  } catch {
    return REQUEST_MESSAGE
  }
}

// Olayları sırayla işler; done ya da error geldiyse true döner.
function dispatch(event: SseEvent, handlers: ChatHandlers): boolean {
  if (event.event === 'delta') {
    const text = field(event.data, 'text')
    if (typeof text === 'string') handlers.onDelta(text)
    return false
  }
  if (event.event === 'done') {
    const reason = field(event.data, 'stop_reason')
    handlers.onDone(typeof reason === 'string' ? reason : null)
    return true
  }
  if (event.event === 'error') {
    const message = field(event.data, 'message')
    handlers.onError(typeof message === 'string' ? message : STREAM_MESSAGE)
    return true
  }
  return false
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
