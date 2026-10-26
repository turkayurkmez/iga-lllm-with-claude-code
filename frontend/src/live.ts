// Harita verisi: GET /map/stands (stand listesi) ve GET /live/positions (canlı konum SSE).
// Sözleşme docs/canli_akis.md › SSE ve › Stand listesi. Sunucunun gönderdiği olduğu gibi
// taşınır: yaş, bayatlık ya da saat burada hesaplanmaz; eksik alan doldurulmaz.

import { parseSse, type SseEvent } from './chat'

export const LIVE_NETWORK_MESSAGE = 'Canlı konum akışına ulaşılamadı.'
export const LIVE_STREAM_MESSAGE = 'Canlı konum akışı kesildi.'
export const STANDS_MESSAGE = 'Stand listesi alınamadı.'

// Konum görünümü: alan adları radar biçimindedir, kayıt alanları olduğu gibi gelir;
// stale/age_s/final sunucudan gelir ve saat yoksa stale/age_s bulunmaz.
export type Position = Record<string, unknown> & {
  Key: string
  Flight: string
  Latitude: number
  Longitude: number
}

export type Stand = Record<string, unknown> & {
  stand_code: string
  lat: number
  lon: number
}

export interface LiveHandlers {
  onSnapshot: (positions: Position[], status: string | null) => void
  // position ve stale olayları aynı görünümü taşır.
  onPosition: (position: Position) => void
  onRemoved: (key: string) => void
  onStatus: (state: string) => void
  // Sunucunun simüle saati (`clock.now`, ISO dizesi olduğu gibi).
  onClock: (now: string) => void
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

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function isPosition(value: unknown): value is Position {
  return (
    isRecord(value) &&
    typeof value.Key === 'string' &&
    typeof value.Flight === 'string' &&
    isNumber(value.Latitude) &&
    isNumber(value.Longitude)
  )
}

export function isStand(value: unknown): value is Stand {
  return (
    isRecord(value) &&
    typeof value.stand_code === 'string' &&
    isNumber(value.lat) &&
    isNumber(value.lon)
  )
}

// Olayı işler; biçimi bozuk olay atlanır, bilinmeyen olay yok sayılır.
export function dispatchLive(event: SseEvent, handlers: LiveHandlers): void {
  const data = parseData(event.data)
  if (data === null) return
  switch (event.event) {
    case 'snapshot':
      if (Array.isArray(data.positions)) {
        // status {state} nesnesi, clock {now, epoch, speed} nesnesi ya da null gelir.
        const state = isRecord(data.status) ? data.status.state : null
        handlers.onSnapshot(data.positions.filter(isPosition), typeof state === 'string' ? state : null)
        if (isRecord(data.clock) && typeof data.clock.now === 'string') {
          handlers.onClock(data.clock.now)
        }
      }
      return
    case 'clock':
      if (typeof data.now === 'string') handlers.onClock(data.now)
      return
    case 'position':
    case 'stale':
      if (isPosition(data)) handlers.onPosition(data)
      return
    case 'removed':
      if (typeof data.Key === 'string') handlers.onRemoved(data.Key)
      return
    case 'status':
      if (typeof data.state === 'string') handlers.onStatus(data.state)
      return
    default:
      return
  }
}

async function detailOf(response: Response, fallback: string): Promise<string> {
  try {
    const body = parseData(await response.text())
    return body !== null && typeof body.detail === 'string' ? body.detail : fallback
  } catch {
    return fallback
  }
}

export async function fetchStands(signal: AbortSignal): Promise<Stand[] | { error: string }> {
  try {
    const response = await fetch('/map/stands', { signal })
    if (!response.ok) return { error: await detailOf(response, STANDS_MESSAGE) }
    const body: unknown = await response.json()
    if (!isRecord(body) || !Array.isArray(body.stands)) return { error: STANDS_MESSAGE }
    return body.stands.filter(isStand)
  } catch {
    return { error: STANDS_MESSAGE }
  }
}

// Akış bitene kadar çalışır; bitiş nedenini genel Türkçe mesaj olarak döndürür (iptalde
// çağıran signal.aborted ile ayırır).
// Yeniden bağlanan istemci yine snapshot ile başlar (Last-Event-ID desteklenmez).
export async function connectLive(
  handlers: LiveHandlers,
  signal: AbortSignal,
): Promise<string> {
  let response: Response
  try {
    response = await fetch('/live/positions', { signal })
  } catch {
    return LIVE_NETWORK_MESSAGE
  }
  if (!response.ok || response.body === null) {
    return detailOf(response, LIVE_NETWORK_MESSAGE)
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      const parsed = parseSse(buffer + value)
      buffer = parsed.rest
      for (const event of parsed.events) dispatchLive(event, handlers)
    }
  } catch {
    return LIVE_STREAM_MESSAGE
  }
  return LIVE_STREAM_MESSAGE
}
