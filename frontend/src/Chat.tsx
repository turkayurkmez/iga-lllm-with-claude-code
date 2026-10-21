// Sohbet sayfası: POST /chat ile tek mesaj gönderir, yanıtı akışla gösterir.
// /chat durumsuzdur; ekrandaki önceki mesajlar modele iletilmez.

import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { streamChat } from './chat'

interface Turn {
  id: number
  question: string
  answer: string
  stopReason: string | null
  error: string | null
  pending: boolean
}

function Chat() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const [nextId, setNextId] = useState(1)

  const pending = turns.some((turn) => turn.pending)
  const message = draft.trim()

  function update(id: number, change: (turn: Turn) => Partial<Turn>) {
    setTurns((current) =>
      current.map((turn) => (turn.id === id ? { ...turn, ...change(turn) } : turn)),
    )
  }

  async function send(event: FormEvent) {
    event.preventDefault()
    if (message === '' || pending) return

    const id = nextId
    setNextId(id + 1)
    setDraft('')
    setTurns((current) => [
      ...current,
      { id, question: message, answer: '', stopReason: null, error: null, pending: true },
    ])

    await streamChat(message, {
      onDelta: (text) => update(id, (turn) => ({ answer: turn.answer + text })),
      onDone: (stopReason) => update(id, () => ({ stopReason, pending: false })),
      onError: (error) => update(id, () => ({ error, pending: false })),
    })
  }

  return (
    <main>
      <header>
        <p>
          <Link to="/">← Doğrulama sayfası</Link>
        </p>
        <h1>Sohbet</h1>
        <p className="note">
          Her soru bağımsız gönderilir; önceki mesajlar modele iletilmez. Copilot'un şu an
          canlı veri erişimi yoktur.
        </p>
      </header>

      <section className="turns" aria-live="polite">
        {turns.map((turn) => (
          <article key={turn.id} className="turn">
            <p className="question">{turn.question}</p>
            <div className="answer">
              {turn.answer !== '' && <p className="answer-text">{turn.answer}</p>}
              {turn.pending && turn.answer === '' && <p className="note">Yanıt bekleniyor…</p>}
              {turn.error !== null && <p className="notice">{turn.error}</p>}
              {turn.stopReason !== null && <p className="stop">{turn.stopReason}</p>}
            </div>
          </article>
        ))}
      </section>

      <form className="composer" onSubmit={send}>
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
    </main>
  )
}

export default Chat
