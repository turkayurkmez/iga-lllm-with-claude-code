// Sohbet sayfası: POST /chat ile tek soru gönderir, olay akışını gösterir.
// Kurallar docs/chat.md › Arayüz kuralları'ndadır: cevap metni, kartlar ve kaynak
// çipleri olay verisinden olduğu gibi çizilir; sayı, saat ya da durum hesaplanmaz.
// /chat durumsuzdur; ekrandaki önceki mesajlar modele iletilmez.

import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import {
  sendFeedback,
  streamChat,
  type Candidate,
  type Done,
  type KpiCard,
  type SelectedObject,
  type SelectionCard,
  type SourceChip,
} from './chat'
import { MapBanner, MapView, useMapData, type FocusRequest, type Highlight } from './Map'

interface Turn {
  id: number
  question: string
  // Mesajla giden harita bağlamı (gönderim anındaki seçim); sonradan değişmez.
  context: SelectedObject | null
  toolCalls: number
  chips: SourceChip[]
  kpis: KpiCard[]
  selections: SelectionCard[]
  answer: string
  done: Done | null
  error: string | null
  pending: boolean
  feedback: FeedbackState
}

// Geri bildirim durumu: gönderilince geri alınamaz, başarısızsa yeniden denenebilir.
type FeedbackState = 'idle' | 'sending' | 'sent' | 'failed'

const CANDIDATE_COLUMNS = ['flight_no', 'callsign', 'registration', 'movement_type'] as const
const ISO_TIME = /^\d{4}-\d{2}-\d{2}T(\d{2}:\d{2})/

// ISO zamanın HH:MM kısmı, zarftaki +03:00 saatiyle; tarayıcı saatine çevrilmez.
function clock(iso: unknown): string | null {
  if (typeof iso !== 'string') return null
  return ISO_TIME.exec(iso)?.[1] ?? null
}

// Seçilen aday için yeni soru: orijinal soru ile adayın sefer no ve tescili, zarftaki
// yazımıyla (docs/chat.md › Arayüz kuralları 3).
function followUp(question: string, candidate: Candidate): string {
  const parts = [candidate.flight_no, candidate.registration].filter(
    (part): part is string => typeof part === 'string',
  )
  return `${question} (${parts.join(' / ')})`
}

function ContextChip({ context, onRemove }: { context: SelectedObject; onRemove?: () => void }) {
  return (
    <span className="context-chip" title={context.object_type === 'flight' ? 'Uçuş' : 'Stand'}>
      Bağlam: {context.id}
      {onRemove !== undefined && (
        <button type="button" onClick={onRemove} aria-label="Bağlamı kaldır">
          ×
        </button>
      )}
    </span>
  )
}

function Chips({ chips }: { chips: SourceChip[] }) {
  return (
    <ul className="chips" aria-label="Kaynak">
      {chips.map((chip, index) => (
        <li key={index} className={chip.stale ? 'chip stale' : 'chip'}>
          <span>{chip.source}</span>
          {clock(chip.as_of) !== null && <span> · {clock(chip.as_of)}</span>}
          {chip.stale && <strong> · eski veri</strong>}
          {chip.error_code !== null && <code>{chip.error_code}</code>}
        </li>
      ))}
    </ul>
  )
}

// Yalnızca olumsuz geri bildirim vardır; not istenmez (docs/audit.md › Arayüz kuralları).
function Feedback({ state, onSend }: { state: FeedbackState; onSend: () => void }) {
  return (
    <div className="feedback">
      <button
        type="button"
        className="thumbs-down"
        disabled={state === 'sending' || state === 'sent'}
        onClick={onSend}
        aria-label="Cevap yanlış"
        title="Cevap yanlış"
      >
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <path
            d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.7a2 2 0 0 0-2 1.7l-1.4 9A2 2 0 0 0 4.3 15H10zM17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      {state === 'sent' && <span className="note">Geri bildiriminiz alındı.</span>}
      {state === 'failed' && <span className="notice warn">Geri bildirim gönderilemedi.</span>}
    </div>
  )
}

function Kpi({ card }: { card: KpiCard }) {
  return (
    <table className="kpi">
      <tbody>
        {card.items.map((item) => (
          <tr key={item.field}>
            <td>{item.description}</td>
            <td className="kpi-value">{item.value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Selection({
  card,
  disabled,
  onPick,
}: {
  card: SelectionCard
  disabled: boolean
  onPick: (candidate: Candidate) => void
}) {
  return (
    <section className="selection">
      <p className="message">{card.message}</p>
      <div className="candidates">
        <table>
          <thead>
            <tr>
              {CANDIDATE_COLUMNS.map((column) => (
                <th key={column}>{column}</th>
              ))}
              <th>scheduled_time</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {card.candidates.map((candidate) => (
              <tr key={candidate.flight_id}>
                {CANDIDATE_COLUMNS.map((column) => (
                  <td key={column}>
                    {typeof candidate[column] === 'string' ? (
                      String(candidate[column])
                    ) : (
                      <em>veride yok</em>
                    )}
                  </td>
                ))}
                <td>{clock(candidate.scheduled_time) ?? <em>veride yok</em>}</td>
                <td>
                  <button type="button" disabled={disabled} onClick={() => onPick(candidate)}>
                    Bunu sor
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function Chat() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const [nextId, setNextId] = useState(1)
  // Haritadaki tek seçim: kalıcıdır, sonraki mesaja `selected` olarak eklenir.
  const [selected, setSelected] = useState<SelectedObject | null>(null)
  const [highlight, setHighlight] = useState<Highlight | null>(null)
  const [focus, setFocus] = useState<FocusRequest | null>(null)
  const map = useMapData()

  const pending = turns.some((turn) => turn.pending)
  const message = draft.trim()

  function update(id: number, change: (turn: Turn) => Partial<Turn>) {
    setTurns((current) =>
      current.map((turn) => (turn.id === id ? { ...turn, ...change(turn) } : turn)),
    )
  }

  async function ask(question: string) {
    const id = nextId
    setNextId(id + 1)
    setTurns((current) => [
      ...current,
      {
        id,
        question,
        context: selected,
        toolCalls: 0,
        chips: [],
        kpis: [],
        selections: [],
        answer: '',
        done: null,
        error: null,
        pending: true,
        feedback: 'idle',
      },
    ])

    await streamChat(
      question,
      {
      onToolCall: () => update(id, (turn) => ({ toolCalls: turn.toolCalls + 1 })),
      // Komut yalnızca durumu değiştirir; ağ isteği yapmaz. Haritada olmayan nesne atlanır.
      onMapCommand: (command) => {
        if (command.command === 'focus_map_object') {
          if (!map.has(command.object_type, command.id)) return
          setSelected({ object_type: command.object_type, id: command.id })
          setFocus((current) => ({
            object_type: command.object_type,
            id: command.id,
            nonce: (current?.nonce ?? 0) + 1,
          }))
        } else {
          setHighlight({ object_type: command.object_type, ids: command.ids })
        }
      },
      onChip: (chip) => update(id, (turn) => ({ chips: [...turn.chips, chip] })),
      onKpi: (card) => update(id, (turn) => ({ kpis: [...turn.kpis, card] })),
      onSelection: (card) =>
        update(id, (turn) => ({ selections: [...turn.selections, card] })),
      onText: (text) => update(id, (turn) => ({ answer: turn.answer + text })),
      onDone: (done) => update(id, () => ({ done, pending: false })),
      onError: (error) => update(id, () => ({ error, pending: false })),
      },
      selected,
    )
  }

  async function reject(id: number, auditId: string) {
    update(id, () => ({ feedback: 'sending' }))
    const ok = await sendFeedback(auditId)
    update(id, () => ({ feedback: ok ? 'sent' : 'failed' }))
  }

  function send(event: FormEvent) {
    event.preventDefault()
    if (message === '' || pending) return
    setDraft('')
    void ask(message)
  }

  return (
    <main className="chat-page">
      <div className="chat-layout">
      <div className="chat-column">
      <header>
        <p>
          <Link to="/">← Doğrulama sayfası</Link>
        </p>
        <h1>Sohbet</h1>
        <p className="note">Her soru bağımsız gönderilir; önceki mesajlar modele iletilmez.</p>
      </header>

      <section className="turns" aria-live="polite">
        {turns.map((turn) => {
          // error'dan önce gelen çip ve kartlar cevap sayılmaz (Arayüz kuralları 4).
          const showCards = turn.error === null
          // Geri bildirim yalnızca tamam'da ve audit satırı yazıldıysa (audit_id dolu).
          const auditId =
            turn.error === null && turn.done?.status === 'tamam' ? turn.done.audit_id : null
          return (
            <article key={turn.id} className="turn">
              <p className="question">{turn.question}</p>
              {turn.context !== null && <ContextChip context={turn.context} />}
              <div className="answer">
                {turn.answer !== '' && <p className="answer-text">{turn.answer}</p>}
                {turn.pending && turn.answer === '' && (
                  <p className="note">
                    Yanıt bekleniyor…
                    {turn.toolCalls > 0 && ` (${turn.toolCalls} veri sorgusu)`}
                  </p>
                )}
                {turn.done?.status === 'tamam' && turn.answer === '' && (
                  <p className="note">Cevap üretilmedi.</p>
                )}
                {auditId !== null && (
                  <Feedback state={turn.feedback} onSend={() => void reject(turn.id, auditId)} />
                )}
                {turn.error !== null && <p className="notice warn">{turn.error}</p>}
                {showCards && turn.kpis.map((card, index) => <Kpi key={index} card={card} />)}
                {showCards &&
                  turn.selections.map((card, index) => (
                    <Selection
                      key={index}
                      card={card}
                      disabled={pending}
                      onPick={(candidate) => void ask(followUp(turn.question, candidate))}
                    />
                  ))}
                {showCards && turn.chips.length > 0 && <Chips chips={turn.chips} />}
                {turn.done !== null && (
                  <p className="stop">
                    talimat {turn.done.instruction.name} ({turn.done.instruction.version})
                  </p>
                )}
              </div>
            </article>
          )
        })}
      </section>

      <form className="composer" onSubmit={send}>
        {selected !== null && (
          <div className="composer-context">
            <ContextChip context={selected} onRemove={() => setSelected(null)} />
          </div>
        )}
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              event.currentTarget.form?.requestSubmit()
            }
          }}
          placeholder="Mesajınızı yazın (Enter gönderir, Shift+Enter yeni satır)"
          rows={3}
          aria-label="Mesaj"
        />
        <button type="submit" className="primary" disabled={message === '' || pending}>
          {pending ? 'Yanıt geliyor…' : 'Gönder'}
        </button>
      </form>
      </div>

      <aside className="map-panel" aria-label="Harita">
        <MapBanner data={map} />
        <MapView
          data={map}
          selected={selected}
          highlight={highlight}
          focus={focus}
          onSelect={setSelected}
        />
      </aside>
      </div>
    </main>
  )
}

export default Chat
