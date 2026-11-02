import { useEffect, useState } from 'react'

/* Minimal markdown so no raw * or _ is ever shown to the elder. */
function renderText(text) {
  if (!text) return null
  const lines = String(text).split('\n')
  const nodes = []
  let list = []
  const flush = (key) => {
    if (list.length) {
      nodes.push(<ul key={'u' + key} style={{ margin: '6px 0', paddingLeft: 22 }}>{list}</ul>)
      list = []
    }
  }
  const inline = (s) => {
    const parts = []
    const re = /(\*\*[^*]+\*\*|__[^_]+__|_[^_\n]+_|\*[^*\n]+\*)/g
    let last = 0, m
    while ((m = re.exec(s)) !== null) {
      if (m.index > last) parts.push(s.slice(last, m.index))
      const tok = m[0]
      if (tok.startsWith('**') || tok.startsWith('__')) {
        parts.push(<b key={m.index}>{tok.slice(2, -2)}</b>)
      } else {
        parts.push(<i key={m.index}>{tok.slice(1, -1)}</i>)
      }
      last = m.index + tok.length
    }
    if (last < s.length) parts.push(s.slice(last))
    return parts
  }
  lines.forEach((raw, i) => {
    const line = raw.trimEnd()
    if (/^\s*[-•]\s+/.test(line)) {
      list.push(<li key={i}>{inline(line.replace(/^\s*[-•]\s+/, ''))}</li>)
      return
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      list.push(<li key={i}>{inline(line.replace(/^\s*\d+[.)]\s+/, ''))}</li>)
      return
    }
    flush(i)
    if (!line.trim()) { nodes.push(<div key={'b' + i} style={{ height: 8 }} />); return }
    nodes.push(<div key={i}>{inline(line)}</div>)
  })
  flush('end')
  return <div>{nodes}</div>
}

function Typewriter({ text }) {
  const [n, setN] = useState(0)
  useEffect(() => {
    setN(0)
    const id = setInterval(() => setN((x) => {
      if (x >= text.length) { clearInterval(id); return x }
      return x + Math.max(1, Math.round(text.length / 90))
    }), 12)
    return () => clearInterval(id)
  }, [text])
  return <div>{renderText(text.slice(0, n))}</div>
}

function TriageCard({ triage, t, note }) {
  const cls = triage.severity >= 7 ? 'hi' : triage.severity >= 4 ? 'mid' : 'low'
  return (
    <div className={'scard' + (triage.severity >= 7 ? ' danger' : '')}
         style={{ textAlign: 'left' }}>
      <h4 className={cls}>
        {t('emergency')} · {triage.category}
        <span className="sev">severity {triage.severity}/10</span>
      </h4>
      <div>{renderText(triage.calm_reply)}</div>
      {triage.home_care?.length > 0 && (
        <>
          <div style={{ marginTop: 10, fontWeight: 600 }}>{t('home_care')}</div>
          <ul className="care">{triage.home_care.map((c, i) => <li key={i}>{c}</li>)}</ul>
        </>
      )}
      {triage.red_flags?.length > 0 && (
        <div style={{ marginTop: 8 }}>
          {triage.red_flags.map((f, i) => (
            <span className="flag" key={i}>⚠ {f}</span>
          ))}
        </div>
      )}
      {triage.doctor_call && (
        <div style={{ marginTop: 10, fontWeight: 600 }}>{t('ask_doctor')}</div>
      )}
      {note ? <div className="note">{note}</div> : null}
    </div>
  )
}

export default function ChatView({ msgs, typing, t, draft, setDraft, onSend,
  onMic, recording, recMs, onAttach, busy }) {
  const box = (m, i, last) => {
    if (m.role === 'user') return <div className="msg me" key={i}>{m.text}</div>
    if (m.kind === 'triage') {
      return (
        <div className="msg you" key={i}>
          <TriageCard triage={m.triage} t={t} note={m.note} />
        </div>
      )
    }
    return (
      <div className="msg you" key={i}>
        {last && m.stream ? <Typewriter text={m.text} /> : renderText(m.text)}
        {m.actions?.length ? (
          <div style={{ marginTop: 8 }}>
            {m.actions.map((a, k) => <span className="chip" key={k} style={{ marginRight: 6 }}>{a}</span>)}
          </div>
        ) : null}
        {m.note ? <div className="note">{m.note}</div> : null}
      </div>
    )
  }

  return (
    <>
      <div className="msgs">
        <div className="wrap">
          {msgs.map((m, i) => box(m, i, i === msgs.length - 1))}
          {typing && (
            <div className="msg you">
              <span className="typing"><i /><i /><i /></span>
            </div>
          )}
        </div>
      </div>
      <div className="composer">
        <div className="wrap">
          <div className="box">
            <textarea
              rows={1}
              value={draft}
              placeholder={t('ask')}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSend() }
              }}
            />
            <button className="iconbtn" title={t('scan')}
                    onClick={() => document.getElementById('scanfile')?.click()}>📎</button>
            <input id="scanfile" type="file" accept="image/*" hidden
                   onChange={(e) => { if (e.target.files?.[0]) onAttach(e.target.files[0]) }} />
            <button className="iconbtn" title={t('listening')} onClick={onMic}>
              {recording ? `⏹ ${(recMs / 1000).toFixed(1)}s` : '🎙️'}
            </button>
            <button className="send" onClick={onSend} disabled={busy || !draft.trim()}>↑</button>
          </div>
        </div>
      </div>
    </>
  )
}
