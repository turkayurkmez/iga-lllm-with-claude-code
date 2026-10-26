// Sohbet sayfasındaki SVG harita (docs/harita.md, docs/canli_akis.md). Stand'ler
// GET /map/stands'ten, uçaklar GET /live/positions SSE'sinden çizilir. Sunucunun
// gönderdiği olduğu gibi gösterilir: yaş, bayatlık ve saat hesaplanmaz, konum
// kaydırılmaz. Koordinatlar yalnızca ekrana yerleştirmek için SVG'ye çevrilir.

import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react'
import type { ObjectType, SelectedObject } from './chat'
import {
  connectLive,
  fetchStands,
  type Position,
  type Stand,
} from './live'

const VIEW_W = 800
const VIEW_H = 600
const PAD = 40
const FOCUS_ZOOM = 4
const MIN_ZOOM = 1
const MAX_ZOOM = 16
const RETRY_MS = 5000
const DRAG_PX = 4

export interface FocusRequest {
  object_type: ObjectType
  id: string
  // Aynı nesneye art arda gelen komutlar da ortalansın diye her komutta artar.
  nonce: number
}

export interface Highlight {
  object_type: ObjectType
  ids: string[]
}

export interface MapData {
  stands: Stand[]
  positions: Map<string, Position>
  status: string | null
  // Stand listesi ya da canlı akış hakkında sunucunun/istemcinin genel mesajı.
  notice: string | null
  // Stand listesinin alınamadığını söyleyen genel mesaj.
  standsNotice: string | null
  // Sunucunun son simüle saati (`clock.now`) olduğu gibi; saat yoksa null.
  clockNow: string | null
  // Akış durmuş: status `yayinda` değil ya da canlı bağlantı kesik.
  stopped: boolean
  ready: boolean
  has: (objectType: ObjectType, id: string) => boolean
}

// Stand listesini bir kez, konumları sürekli okur. Konumlar ref'te tutulur, render
// requestAnimationFrame ile birleştirilir (olay başına render yok).
export function useMapData(): MapData {
  const [stands, setStands] = useState<Stand[]>([])
  const [standsDone, setStandsDone] = useState(false)
  const [liveDone, setLiveDone] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [standsNotice, setStandsNotice] = useState<string | null>(null)
  const [clockNow, setClockNow] = useState<string | null>(null)
  const [view, setView] = useState<Map<string, Position>>(() => new Map())
  const positions = useRef(new Map<string, Position>())
  const standsRef = useRef<Stand[]>([])
  const frame = useRef<number | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller

    function schedule() {
      if (frame.current !== null) return
      frame.current = requestAnimationFrame(() => {
        frame.current = null
        setView(new Map(positions.current))
      })
    }

    void fetchStands(signal).then((result) => {
      if (signal.aborted) return
      if (Array.isArray(result)) {
        standsRef.current = result
        setStands(result)
      } else {
        setStandsNotice(result.error)
      }
      setStandsDone(true)
    })

    void (async () => {
      while (!signal.aborted) {
        const message = await connectLive(
          {
            onSnapshot: (list, state) => {
              positions.current = new Map(list.map((position) => [position.Key, position]))
              if (state !== null) setStatus(state)
              setNotice(null)
              setLiveDone(true)
              schedule()
            },
            onPosition: (position) => {
              positions.current.set(position.Key, position)
              schedule()
            },
            onRemoved: (key) => {
              positions.current.delete(key)
              schedule()
            },
            onStatus: setStatus,
            onClock: setClockNow,
          },
          signal,
        )
        if (signal.aborted) return
        setNotice(message)
        setLiveDone(true)
        await new Promise((resolve) => setTimeout(resolve, RETRY_MS))
      }
    })()

    return () => {
      controller.abort()
      if (frame.current !== null) cancelAnimationFrame(frame.current)
      frame.current = null
    }
  }, [])

  return {
    stands,
    positions: view,
    status,
    notice,
    standsNotice,
    clockNow,
    stopped: (status !== null && status !== 'yayinda') || notice !== null,
    ready: standsDone && liveDone,
    has: (objectType, id) =>
      objectType === 'stand'
        ? standsRef.current.some((stand) => stand.stand_code === id)
        : [...positions.current.values()].some((position) => position.Flight === id),
  }
}

interface Bounds {
  minLat: number
  maxLat: number
  minLon: number
  maxLon: number
}

function boundsOf(stands: Stand[], positions: Iterable<Position>): Bounds | null {
  const lats: number[] = []
  const lons: number[] = []
  for (const stand of stands) {
    lats.push(stand.lat)
    lons.push(stand.lon)
  }
  for (const position of positions) {
    lats.push(position.Latitude)
    lons.push(position.Longitude)
  }
  if (lats.length === 0) return null
  return {
    minLat: Math.min(...lats),
    maxLat: Math.max(...lats),
    minLon: Math.min(...lons),
    maxLon: Math.max(...lons),
  }
}

type Project = (lat: number, lon: number) => [number, number]

// Eşdikdörtgen izdüşüm: boylam enleme göre cos(orta enlem) ile daraltılır.
function makeProject(bounds: Bounds): Project {
  const lonScale = Math.cos((((bounds.minLat + bounds.maxLat) / 2) * Math.PI) / 180)
  const spanX = (bounds.maxLon - bounds.minLon) * lonScale
  const spanY = bounds.maxLat - bounds.minLat
  const scale = Math.min(
    spanX > 0 ? (VIEW_W - 2 * PAD) / spanX : Infinity,
    spanY > 0 ? (VIEW_H - 2 * PAD) / spanY : Infinity,
  )
  const unit = Number.isFinite(scale) ? scale : 1
  const offsetX = (VIEW_W - spanX * unit) / 2
  const offsetY = (VIEW_H - spanY * unit) / 2
  return (lat, lon) => [
    offsetX + (lon - bounds.minLon) * lonScale * unit,
    offsetY + (bounds.maxLat - lat) * unit,
  ]
}

const STATE_TEXT: Record<string, string> = {
  bitti: 'akış tamamlandı',
  koptu: 'yayıncı beklenmedik şekilde koptu',
  broker_yok: 'broker bağlantısı yok',
}
const CLOCK_TIME = /T(\d{2}:\d{2}:\d{2})/

// Akış durduğunda haritanın üstündeki bant; saat sunucunun son `clock.now` değeridir,
// tarayıcı saati okunmaz. Akış sürüyorsa yalnızca stand listesi hatası görünebilir.
export function MapBanner({ data }: { data: MapData }) {
  const last = data.clockNow === null ? null : (CLOCK_TIME.exec(data.clockNow)?.[1] ?? null)
  return (
    <>
      {data.stopped && (
        <p className="map-banner" role="status">
          <strong>Akış durdu</strong>
          {data.notice !== null
            ? ` — ${data.notice}`
            : ` (${data.status}): ${STATE_TEXT[data.status ?? ''] ?? data.status}`}
          {last !== null && ` · son saat ${last}`}
        </p>
      )}
      {data.standsNotice !== null && data.ready && (
        <p className="notice warn">{data.standsNotice}</p>
      )}
    </>
  )
}

function detail(record: Record<string, unknown>): string {
  return Object.entries(record)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join('\n')
}

interface MapViewProps {
  data: MapData
  selected: SelectedObject | null
  highlight: Highlight | null
  focus: FocusRequest | null
  onSelect: (selection: SelectedObject | null) => void
}

export function MapView({ data, selected, highlight, focus, onSelect }: MapViewProps) {
  const [center, setCenter] = useState<[number, number]>([VIEW_W / 2, VIEW_H / 2])
  const [zoom, setZoom] = useState(MIN_ZOOM)
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null)
  const dragged = useRef(false)
  const handled = useRef<number | null>(null)
  // Odak komutu verilen uçuş: konum geldikçe harita onu ortalar. Elle kaydırma, Tümü
  // ya da seçimin başka nesneye geçmesi takibi bırakır.
  const [follow, setFollow] = useState<string | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  // Sınırlar ilk veri geldiğinde bir kez sabitlenir; uçaklar hareket ettikçe harita kaymaz.
  const bounds = useMemo(
    () => (data.ready ? boundsOf(data.stands, data.positions.values()) : null),
    // positions ref'tir; ready true olurken dolu olan anki hali kullanılır.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data.ready, data.stands],
  )
  const project = useMemo(() => (bounds === null ? null : makeProject(bounds)), [bounds])

  useEffect(() => {
    if (focus === null || project === null || handled.current === focus.nonce) return
    handled.current = focus.nonce
    let target: [number, number] | null = null
    if (focus.object_type === 'stand') {
      const stand = data.stands.find((item) => item.stand_code === focus.id)
      if (stand !== undefined) target = project(stand.lat, stand.lon)
    } else {
      for (const position of data.positions.values()) {
        if (position.Flight === focus.id) {
          target = project(position.Latitude, position.Longitude)
          break
        }
      }
    }
    // İstemcide bulunmayan nesne sessizce atlanır.
    if (target === null) return
    setCenter(target)
    setZoom((current) => Math.max(current, FOCUS_ZOOM))
    setFollow(focus.object_type === 'flight' ? focus.id : null)
  }, [focus, project, data.stands, data.positions])

  useEffect(() => {
    if (follow === null || project === null) return
    if (selected?.object_type !== 'flight' || selected.id !== follow) {
      setFollow(null)
      return
    }
    for (const position of data.positions.values()) {
      if (position.Flight === follow) {
        setCenter(project(position.Latitude, position.Longitude))
        return
      }
    }
  }, [follow, selected, project, data.positions])

  // Tekerlek ile yakınlaştırma; sayfa kaymasın diye pasif olmayan dinleyici gerekir.
  const mapped = project !== null
  useEffect(() => {
    const svg = svgRef.current
    if (svg === null) return
    function onWheel(event: WheelEvent) {
      event.preventDefault()
      setZoom((current) =>
        Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current * (event.deltaY < 0 ? 1.25 : 0.8))),
      )
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
  }, [mapped])

  if (project === null) {
    return (
      <div className="map-empty">
        {data.notice ?? data.standsNotice ?? 'Harita verisi bekleniyor…'}
      </div>
    )
  }

  const k = 1 / zoom
  const viewW = VIEW_W * k
  const viewH = VIEW_H * k
  const viewBox = `${center[0] - viewW / 2} ${center[1] - viewH / 2} ${viewW} ${viewH}`

  const lit = new Set((highlight?.ids ?? []).map((id) => `${highlight?.object_type}:${id}`))
  const isLit = (type: ObjectType, id: string) => lit.has(`${type}:${id}`)
  const isSelected = (type: ObjectType, id: string) =>
    selected !== null && selected.object_type === type && selected.id === id

  function choose(type: ObjectType, id: string) {
    if (dragged.current) return
    onSelect(isSelected(type, id) ? null : { object_type: type, id })
  }

  function onPointerDown(event: PointerEvent<SVGSVGElement>) {
    drag.current = { x: event.clientX, y: event.clientY, moved: false }
    dragged.current = false
  }

  function onPointerMove(event: PointerEvent<SVGSVGElement>) {
    const start = drag.current
    if (start === null) return
    const dx = event.clientX - start.x
    const dy = event.clientY - start.y
    if (!start.moved && Math.hypot(dx, dy) < DRAG_PX) return
    // Yakalama yalnızca sürüklemede başlar; pointerdown'da yakalansa tıklama olayı
    // uçağa değil SVG'ye gider ve seçim çalışmaz.
    if (!start.moved) event.currentTarget.setPointerCapture(event.pointerId)
    start.moved = true
    dragged.current = true
    setFollow(null)
    const rect = event.currentTarget.getBoundingClientRect()
    const unit = viewW / rect.width
    setCenter(([x, y]) => [x - dx * unit, y - dy * unit])
    start.x = event.clientX
    start.y = event.clientY
  }

  function onPointerUp() {
    drag.current = null
  }

  function zoomBy(factor: number) {
    setZoom((current) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current * factor)))
  }

  function reset() {
    setFollow(null)
    setCenter([VIEW_W / 2, VIEW_H / 2])
    setZoom(MIN_ZOOM)
  }

  return (
    <div className={data.stopped ? 'map frozen' : 'map'}>
      <div className="map-tools">
        <button type="button" onClick={() => zoomBy(2)} aria-label="Yakınlaştır">
          +
        </button>
        <button type="button" onClick={() => zoomBy(0.5)} aria-label="Uzaklaştır">
          −
        </button>
        <button type="button" onClick={reset}>
          Tümü
        </button>
      </div>
      <svg
        ref={svgRef}
        viewBox={viewBox}
        role="img"
        aria-label="Havalimanı haritası"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <rect
          className="map-bg"
          x={center[0] - viewW / 2}
          y={center[1] - viewH / 2}
          width={viewW}
          height={viewH}
          onClick={() => {
            if (!dragged.current) onSelect(null)
          }}
        />
        {data.stands.map((stand) => {
          const [x, y] = project(stand.lat, stand.lon)
          const classes = ['stand']
          if (isLit('stand', stand.stand_code)) classes.push('lit')
          if (isSelected('stand', stand.stand_code)) classes.push('selected')
          return (
            <g
              key={stand.stand_code}
              className={classes.join(' ')}
              transform={`translate(${x} ${y})`}
              onClick={(event) => {
                event.stopPropagation()
                choose('stand', stand.stand_code)
              }}
            >
              <title>{detail(stand)}</title>
              <rect x={-5 * k} y={-5 * k} width={10 * k} height={10 * k} strokeWidth={k} />
              <text x={8 * k} y={4 * k} fontSize={12 * k}>
                {stand.stand_code}
              </text>
            </g>
          )
        })}
        {[...data.positions.values()].map((position) => {
          const [x, y] = project(position.Latitude, position.Longitude)
          const classes = ['plane']
          if (position.stale === true) classes.push('stale')
          if (isLit('flight', position.Flight)) classes.push('lit')
          if (isSelected('flight', position.Flight)) classes.push('selected')
          const track = typeof position.Track === 'number' ? position.Track : null
          return (
            <g
              key={position.Key}
              className={classes.join(' ')}
              transform={`translate(${x} ${y})`}
              onClick={(event) => {
                event.stopPropagation()
                choose('flight', position.Flight)
              }}
            >
              <title>{detail(position)}</title>
              {track === null ? (
                <circle r={7 * k} strokeWidth={k} />
              ) : (
                <polygon
                  points={`0,${-11 * k} ${7 * k},${8 * k} 0,${4 * k} ${-7 * k},${8 * k}`}
                  transform={`rotate(${track})`}
                  strokeWidth={k}
                />
              )}
              <text x={10 * k} y={-8 * k} fontSize={12 * k}>
                {position.stale === true ? `${position.Flight} · bayat` : position.Flight}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
