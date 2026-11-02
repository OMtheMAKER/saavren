import { useEffect, useRef } from 'react'

export default function Composer({
  t, value, onChange, onSend, onAttach, onMic, recording, recMs, level, busy, fileRef,
}) {
  const ta = useRef(null)

  useEffect(() => {
    const el = ta.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(180, el.scrollHeight) + 'px'
  }, [value])

  const canSend = value.trim().length > 0 && !busy && !recording

  return (
    <div className="composer-wrap">
      <div className="composer">
        <button
          className="icon-btn"
          title="📎 attach"
          onClick={() => fileRef?.current?.click()}
          style={{ fontSize: 16 }}
        >📎</button>

        <textarea
          ref={ta}
          rows={1}
          value={recording ? t('listening') : value}
          placeholder={t('placeholder')}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (canSend) onSend() }
          }}
          readOnly={recording}
        />

        {recording ? (
          <button className="send mic rec" onClick={onMic} title={t('tap_stop')}>
            ■
          </button>
        ) : (
          <button className="send" onClick={onMic} title="🎙">🎙</button>
        )}

        <button className="send" onClick={onSend} disabled={!canSend} title="send">
          {busy ? '…' : '↑'}
        </button>

        <input
          ref={fileRef}
          type="file"
          accept="image/*,application/pdf,.txt"
          style={{ display: 'none' }}
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) onAttach(f)
            e.target.value = ''
          }}
        />
      </div>

      {recording ? (
        <div style={{ maxWidth: 768, margin: '8px auto 0', display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ flex: 1, height: 5, background: 'var(--border)', borderRadius: 4, overflow: 'hidden' }}>
            <div style={{ width: (level * 100).toFixed(0) + '%', height: '100%', background: 'var(--danger)', transition: 'width .08s' }} />
          </div>
          <span style={{ fontSize: 12, color: 'var(--muted)' }}>
            {(recMs / 1000).toFixed(1)}s · {t('tap_stop')}
          </span>
        </div>
      ) : (
        <div className="foot-note">{t('footnote')}</div>
      )}
    </div>
  )
}
