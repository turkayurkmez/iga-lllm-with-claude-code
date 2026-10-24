// /tools doğrulama sayfası: sabit sorguları tek tek ya da toplu çalıştırır ve sonucu
// olduğu gibi gösterir. Kurallar docs/http.md › Arayüz kuralları'dadır: ne gösterileceğine
// error.code ile karar verilir, değer yeniden hesaplanmaz, eksik alan doldurulmaz.

import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import './App.css'
import { ErrorCode, isEnvelope, type Envelope } from './envelope'
import { QUERIES, type Query } from './queries'

const NETWORK_MESSAGE = 'Sunucuya ulaşılamadı.'
const TRANSPORT_MESSAGE = 'İstek iletilemedi.'

type Result =
  | { kind: 'envelope'; status: number; envelope: Envelope }
  | { kind: 'transport'; status: number | null; message: string }

// Yalnızca bu alanlar aday listesinde sütun olarak gösterilir (Arayüz kuralları › Belirsizlik).
const CANDIDATE_COLUMNS = [
  'flight_no',
  'callsign',
  'registration',
  'movement_type',
  'scheduled_time',
] as const

async function callTool(tool: string, body: string): Promise<Result> {
  let response: Response
  try {
    response = await fetch(`/tools/${tool}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
    })
  } catch {
    return { kind: 'transport', status: null, message: NETWORK_MESSAGE }
  }

  let parsed: unknown = undefined
  try {
    parsed = await response.json()
  } catch {
    // Gövde JSON değil; aşağıda taşıma hatası sayılır.
  }
  if (isEnvelope(parsed)) {
    return { kind: 'envelope', status: response.status, envelope: parsed }
  }
  const detail =
    typeof parsed === 'object' && parsed !== null && 'detail' in parsed
      ? parsed.detail
      : undefined
  return {
    kind: 'transport',
    status: response.status,
    message: typeof detail === 'string' ? detail : TRANSPORT_MESSAGE,
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

// Değeri olduğu gibi gösterir: nesne anahtar/değer tablosu, dizi sıralı liste olur.
function Value({ value }: { value: unknown }) {
  if (value === null) return <code className="null">null</code>
  if (Array.isArray(value)) {
    if (value.length === 0) return <code>[]</code>
    return (
      <ol className="array">
        {value.map((item, index) => (
          <li key={index}>
            <Value value={item} />
          </li>
        ))}
      </ol>
    )
  }
  if (isRecord(value)) {
    const entries = Object.entries(value)
    if (entries.length === 0) return <code>{'{}'}</code>
    return (
      <table className="object">
        <tbody>
          {entries.map(([key, item]) => (
            <tr key={key}>
              <th>{key}</th>
              <td>
                <Value value={item} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    )
  }
  if (typeof value === 'string') return <code>{value}</code>
  return <code className="literal">{String(value)}</code>
}

function codeOf(result: Result): string | null {
  return result.kind === 'envelope' ? (result.envelope.error?.code ?? null) : null
}

function Verdict({ query, result }: { query: Query; result: Result }) {
  const { expected } = query
  const matches =
    result.status === expected.status &&
    (result.kind === 'envelope') === expected.envelope &&
    codeOf(result) === expected.code
  return (
    <span className={matches ? 'badge match' : 'badge mismatch'}>
      {matches ? 'uyumlu' : 'uyumsuz'}
    </span>
  )
}

// error.code'a göre gösterilecek açıklama (Arayüz kuralları › Hata ayrımı).
function Notice({ envelope }: { envelope: Envelope }) {
  const { error, filters, stale, as_of } = envelope
  if (stale) {
    return (
      <p className="notice warn">
        Veri güncel değil: değer {as_of} itibarıyla son bilinen değerdir.
      </p>
    )
  }
  if (error === null) return null
  switch (error.code) {
    case ErrorCode.NOT_FOUND:
      return (
        <div className="notice">
          <p>Kayıt bulunamadı. Aranan:</p>
          <Value value={filters} />
        </div>
      )
    case ErrorCode.AMBIGUOUS_ENTITY:
      return <p className="notice">Birden fazla eşleşme var; bir aday seçin.</p>
    case ErrorCode.CAPABILITY_NOT_IN_SCOPE:
      return <p className="notice">Bu iş copilot'un kapsamı dışında.</p>
    case ErrorCode.SCHEMA_VALIDATION_FAILED:
      return (
        <p className="notice">
          İstek şu an yanıtlanamadı; girdi düzeltilip yeniden gönderilebilir.
        </p>
      )
    default:
      return null
  }
}

function Candidates({
  envelope,
  queryId,
}: {
  envelope: Envelope
  queryId: string
}) {
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<Result | null>(null)
  const [running, setRunning] = useState(false)

  if (envelope.error?.code !== ErrorCode.AMBIGUOUS_ENTITY) return null
  if (!Array.isArray(envelope.value)) return null

  async function choose(flightId: string) {
    setSelected(flightId)
    setDetail(null)
    setRunning(true)
    setDetail(
      await callTool('get_flight_details', JSON.stringify({ flight_id: flightId })),
    )
    setRunning(false)
  }

  return (
    <section className="candidates">
      <h4>Adaylar</h4>
      <table>
        <thead>
          <tr>
            {CANDIDATE_COLUMNS.map((column) => (
              <th key={column}>{column}</th>
            ))}
            <th></th>
          </tr>
        </thead>
        <tbody>
          {envelope.value.filter(isRecord).map((candidate, index) => {
            const flightId = candidate.flight_id
            return (
              <tr key={`${queryId}-${index}`}>
                {CANDIDATE_COLUMNS.map((column) => (
                  <td key={column}>
                    {column in candidate ? (
                      <Value value={candidate[column]} />
                    ) : (
                      <em>veride yok</em>
                    )}
                  </td>
                ))}
                <td>
                  {typeof flightId === 'string' && (
                    <button
                      type="button"
                      disabled={running}
                      aria-pressed={selected === flightId}
                      onClick={() => choose(flightId)}
                    >
                      Ayrıntı
                    </button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {selected !== null && (
        <div className="nested">
          <p>
            <code>get_flight_details</code> · <code>{selected}</code>
          </p>
          {running ? <p>Çalışıyor…</p> : detail && <ResultView result={detail} />}
        </div>
      )}
    </section>
  )
}

const ENVELOPE_FIELDS = [
  'value',
  'source',
  'as_of',
  'filters',
  'stale',
  'tool_version',
  'error',
  'author',
] as const

function ResultView({ result, queryId }: { result: Result; queryId?: string }) {
  if (result.kind === 'transport') {
    return (
      <div className="result">
        <p className="status">
          HTTP <strong>{result.status ?? 'yok'}</strong> · taşıma hatası, zarf yok
        </p>
        <p className="notice">{result.message}</p>
      </div>
    )
  }
  const { envelope } = result
  return (
    <div className="result">
      <p className="status">
        HTTP <strong>{result.status}</strong> · error.code{' '}
        <strong>{envelope.error?.code ?? 'null'}</strong>
      </p>
      {envelope.error && <p className="message">{envelope.error.message}</p>}
      <Notice envelope={envelope} />
      <table className="envelope">
        <tbody>
          {ENVELOPE_FIELDS.map((field) => (
            <tr key={field}>
              <th>{field}</th>
              <td>
                <Value value={envelope[field]} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {queryId !== undefined && <Candidates envelope={envelope} queryId={queryId} />}
    </div>
  )
}

function App() {
  const [tools, setTools] = useState<string[] | null>(null)
  const [toolsError, setToolsError] = useState<string | null>(null)
  const [results, setResults] = useState<Record<string, Result>>({})
  const [running, setRunning] = useState<Set<string>>(new Set())

  useEffect(() => {
    fetch('/tools')
      .then((response) => response.json())
      .then((body: unknown) => {
        if (!Array.isArray(body)) throw new Error()
        setTools(body.filter(isRecord).map((tool) => String(tool.name)))
      })
      .catch(() => setToolsError(NETWORK_MESSAGE))
  }, [])

  async function run(query: Query) {
    setRunning((current) => new Set(current).add(query.id))
    const result = await callTool(query.tool, query.body)
    setResults((current) => ({ ...current, [query.id]: result }))
    setRunning((current) => {
      const next = new Set(current)
      next.delete(query.id)
      return next
    })
  }

  async function runAll() {
    // Sırayla: aynı anda yalnızca bir istek.
    for (const query of QUERIES) await run(query)
  }

  const busy = running.size > 0

  return (
    <main>
      <header>
        <h1>/tools doğrulama</h1>
        <p>
          Sabit sorgular <code>POST /tools/&#123;ad&#125;</code> ile gönderilir; HTTP durumu,{' '}
          <code>error.code</code> ve zarf alanları olduğu gibi gösterilir. Beklenen değerler{' '}
          <code>docs/http.md</code>'ye göredir (referans veri, saat 16:22).
        </p>
        <p className="tools">
          GET /tools:{' '}
          {toolsError ?? (tools === null ? 'yükleniyor…' : tools.join(', '))}
        </p>
        <div className="actions">
          <button type="button" className="primary" disabled={busy} onClick={runAll}>
            Tümünü çalıştır
          </button>
          <Link to="/sohbet" className="button">
            Sohbet
          </Link>
        </div>
      </header>

      {QUERIES.map((query) => {
        const result = results[query.id]
        const listed = tools?.includes(query.tool)
        return (
          <article key={query.id} className="card">
            <div className="card-head">
              <div>
                <h2>
                  <code>{query.tool}</code>
                  {tools !== null && (
                    <span className={listed ? 'badge listed' : 'badge unlisted'}>
                      {listed ? "GET /tools'ta var" : "GET /tools'ta yok"}
                    </span>
                  )}
                </h2>
                <p className="note">{query.note}</p>
                <p>
                  Gövde: <code>{query.body}</code>
                </p>
                <p className="expected">
                  Beklenen: HTTP {query.expected.status} ·{' '}
                  {query.expected.envelope
                    ? `error.code ${query.expected.code ?? 'null'}`
                    : 'zarf yok'}
                  {result && <Verdict query={query} result={result} />}
                </p>
              </div>
              <button
                type="button"
                disabled={running.has(query.id)}
                onClick={() => run(query)}
              >
                {running.has(query.id) ? 'Çalışıyor…' : 'Çalıştır'}
              </button>
            </div>
            {result && <ResultView result={result} queryId={query.id} />}
          </article>
        )
      })}
    </main>
  )
}

export default App
