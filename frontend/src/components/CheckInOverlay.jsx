/**
 * D6 — the daily companion checks in first.
 *
 * Three plain questions, in her language, spoken aloud and answered by voice.
 * Deliberately calmer than the fall alarm: this is a grandchild asking how
 * her day went, not an emergency. Nothing here can raise an alarm — if she
 * says something worrying, the *answer* does that on the server, once, with
 * the words she actually used.
 */
import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { browserAsr, startRecording } from '../lib/wavRecorder'

export default function CheckInOverlay({
  kind, questions, t, lang, onDone, onSkip, serverAsr, speak, voiceOut,
}) {
  const [i, setI] = useState(0)
  const [answers, setAnswers] = useState([])
  const [listening, setListening] = useState(false)
  const [heard, setHeard] = useState('')
  const [typing, setTyping] = useState(false)
  const [micErr, setMicErr] = useState(false)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(null)

  // never leave the microphone open — she can dismiss mid-recording
  useEffect(() => () => {
    clearTimeout(autoRef.current)
    try { recRef.current?.stop?.() } catch (e) { /* already stopped */ }
  }, [])

  const q = questions[i]
  const last = i >= questions.length - 1

  // Ask it out loud the moment the question appears — she may be across the
  // room, and this whole feature exists so she doesn't have to come to it.
  useEffect(() => {
    if (q && voiceOut && speak) speak(q, lang)
    setHeard(''); setTyping(false); setDraft(''); setMicErr(false)
  }, [i, q, lang])

  // The mic is a TOGGLE: one tap starts, a second tap stops and transcribes.
  // It used to call stop() on the line after start(), so the recording was
  // always empty, the blob always failed the size check, and the panel fell
  // straight through to "Type instead" — every single time.
  //
  // Both paths are cancellable and time-boxed. Browser ASR has no external
  // handle, so without the race below a recognition that never fires would
  // leave her stuck on a red mic with no way out.
  const recRef = useRef(null)
  const autoRef = useRef(null)
  const cancelRef = useRef(false)
  const MAX_MS = 12000

  async function listen() {
    if (busy) return

    // ---- second tap: stop, and keep whatever was captured ----
    if (listening) {
      cancelRef.current = true
      clearTimeout(autoRef.current)
      setListening(false)
      try {
        const out = await recRef.current?.stop()
        if (serverAsr && out?.blob && out.blob.size >= 2000) {
          const d = await api.transcribe(out.blob)
          if (!cancelRef.current) setHeard(d.text || '')
        }
      } catch (e) { /* nothing usable captured */ }
      recRef.current = null
      return
    }

    // ---- first tap: start listening ----
    cancelRef.current = false
    setHeard(''); setMicErr(false)

    if (!serverAsr) {
      setListening(true)
      const heard = await Promise.race([
        browserAsr(lang).catch(() => ''),
        new Promise((res) => { autoRef.current = setTimeout(() => res(''), MAX_MS) }),
      ])
      clearTimeout(autoRef.current)
      setListening(false)
      if (!cancelRef.current) {
        if (heard) setHeard(heard)
        else setTyping(true)
      }
      return
    }

    try {
      recRef.current = await startRecording(() => {})
      setListening(true)
      autoRef.current = setTimeout(() => listen(), MAX_MS)
    } catch (e) {
      // no mic, or permission denied — say so and offer the keyboard.
      // Switching silently made a missing permission look exactly like a
      // broken button.
      setMicErr(true)
      setTyping(true)
    }
  }

  function next() {
    const text = (heard || draft).trim()
    setAnswers((a) => [...a, { q, a: text }])
    if (last) return finish([...answers, { q, a: text }])
    setI((n) => n + 1)
  }

  async function finish(all) {
    setBusy(true)
    try {
      const d = await api.checkinAnswer(kind, lang, all)
      setDone(d.record)
    } catch (e) {
      setDone({ error: e.message || 'could not save' })
    }
    setBusy(false)
  }

  /* ---------------- finished ---------------- */
  if (done) {
    const worrying = done.mood === 'bad' || (done.flags || []).length
    return (
      <div className="checkin">
        <div className="panel">
          <div className="big">{done.error ? '⚠️' : '🙂'}</div>
          <b>{done.error || t('checkin_done')}</b>
          {!done.error ? (
            <div className="small muted" style={{ marginTop: 6 }}>
              {done.mood && done.mood !== 'unknown' ? t('mood_' + done.mood) : ''}
              {done.flags?.length ? ` · ${done.flags.join(', ')}` : ''}
            </div>
          ) : null}
          {worrying ? (
            <div className="small" style={{ marginTop: 8, color: 'var(--warn)' }}>
              {t('checkin_sent')}
            </div>
          ) : null}
          <button className="btn wide" style={{ marginTop: 14 }}
                  onClick={() => onDone(done)}>{t('done')}</button>
        </div>
      </div>
    )
  }

  return (
    <div className="checkin">
      <div className="panel">
        <div className="row" style={{ gap: 10 }}>
          <div className="ci">🙂</div>
          <div style={{ flex: 1 }}>
            <b>{kind === 'evening' ? t('checkin_evening') : t('checkin_morning')}</b>
            <div className="small muted">{t('checkin_sub')}</div>
          </div>
          <button className="btn ghost small" onClick={() => onSkip(kind)}>
            {t('checkin_skip')}
          </button>
        </div>

        <div className="progress">
          <div style={{ width: `${(i / questions.length) * 100}%` }} />
        </div>
        <div className="small muted">{t('checkin_q', { a: i + 1, b: questions.length })}</div>

        <div className="cq">{q}</div>

        {!typing && !heard ? (
          <button className={'mic' + (listening ? ' on' : '')} onClick={listen}>
            {listening ? '🔴' : '🎙️'}
          </button>
        ) : null}
        {!typing && !heard ? (
          <div className="small muted">{t('checkin_tap')}</div>
        ) : null}

        {heard ? (
          <div className="heard">
            <span className="small muted">{t('checkin_heard')}</span>
            <b>{heard}</b>
          </div>
        ) : null}

        {micErr ? (
          <div className="small" style={{ marginTop: 8, color: 'var(--warn)' }}>
            {t('mic_unavailable')}
          </div>
        ) : null}

        {typing ? (
          <input className="inp" value={draft} autoFocus
                 placeholder={t('checkin_type')}
                 onChange={(e) => setDraft(e.target.value)}
                 onKeyDown={(e) => e.key === 'Enter' && draft.trim() && next()} />
        ) : null}

        <div className="row" style={{ gap: 8, marginTop: 14 }}>
          {!typing && !heard ? (
            <button className="btn ghost" onClick={() => setTyping(true)}>
              ⌨️ {t('checkin_type')}
            </button>
          ) : null}
          {(heard || draft.trim()) ? (
            <button className="btn" onClick={next} disabled={busy}>
              {busy ? '…' : last ? '✓ ' + t('checkin_done') : t('checkin_next')}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  )
}
