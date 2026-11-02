export default function HomeView({ t, state, onAsk, onGo, onTestThud,
                                    checkinDue, onStartCheckin }) {
  const p = state?.profile || {}
  const meds = state?.meds || []
  const due = meds.filter((m) => !m.taken).length

  // D6 — today's companion check-ins
  const today = new Date().toISOString().slice(0, 10)
  const cks = (state?.checkins || []).filter((c) =>
    new Date((c.ts || 0) * 1000).toISOString().slice(0, 10) === today)
  const answered = cks.filter((c) => c.status === 'answered')
  const missed = cks.filter((c) => c.status === 'missed')
  const moodIcon = { good: '🙂', ok: '😐', bad: '🤒', unknown: '💬' }

  return (
    <div className="wrap">
      <div className="hero">
        <div>
          <div className="big">{t('welcome')}, {p.name?.split(' ')[0]}</div>
          <div className="muted small">{t('welcome_sub')}</div>
        </div>
      </div>

      <div className="bar" onClick={onAsk}>
        <span style={{ fontSize: 18 }}>💬</span>
        <input readOnly placeholder={t('ask')} />
        <span className="chip">{t('send')}</span>
      </div>

      <div className="grid four" style={{ marginTop: 16 }}>
        <button className="tile" onClick={() => onGo('chat')}>
          <span className="ic">💬</span><b>{t('new_chat')}</b>
          <span>{t('welcome_sub')}</span>
        </button>
        <button className="tile" onClick={() => onGo('meds')}>
          <span className="ic">💊</span><b>{t('medicines')}</b>
          <span>{due ? `${due} ${t('taken')}?` : (meds.length ? t('meds_up_to_date') : t('empty'))}</span>
        </button>
        <button className="tile" onClick={() => onGo('health')}>
          <span className="ic">❤️</span><b>{t('health')}</b>
          <span>{t('recent')}</span>
        </button>
        <button className="tile" onClick={() => onGo('activity')}>
          <span className="ic">🕘</span><b>{t('activity')}</b>
          <span>{t('recent')}</span>
        </button>
      </div>

      {/* ---- D6: the companion's daily check-in ---- */}
      <div className="card" style={{ marginTop: 16 }}>
        <div className="row">
          <b style={{ flex: 1 }}>🙂 {t('checkin_today')}</b>
          {/* always available: she can report how she feels at any hour,
              not only when the clock says so */}
          <button className={'btn small' + (checkinDue ? '' : ' ghost')}
                  onClick={onStartCheckin}>
            {t('checkin_start')}
          </button>
        </div>
        {answered.length === 0 && missed.length === 0 && !checkinDue ? (
          <div className="small muted" style={{ marginTop: 8 }}>
            {t('checkin_none')}
          </div>
        ) : null}
        {answered.map((c) => (
          <div className="ckrow" key={c.id}>
            <span>{moodIcon[c.mood] || '💬'}</span>
            <span className="grow small">
              <b>{c.kind === 'evening' ? t('checkin_evening') : t('checkin_morning')}</b>
              <div className="muted">
                {c.mood ? t('mood_' + c.mood) : ''}
                {c.flags?.length ? ` · ${c.flags.join(', ')}` : ''}
              </div>
            </span>
            <span className="chip done">{t('taken')}</span>
          </div>
        ))}
        {missed.map((c) => (
          <div className="ckrow" key={c.id}>
            <span>🔕</span>
            <span className="grow small" style={{ color: 'var(--warn)' }}>
              {t('checkin_missed', { kind: c.kind })}
            </span>
          </div>
        ))}
        {checkinDue ? (
          <div className="small" style={{ marginTop: 8, color: 'var(--accent)' }}>
            ⏰ {t('checkin_waiting')}
          </div>
        ) : null}
      </div>

      <div className="grid two" style={{ marginTop: 16 }}>
        <div className="card">
          <b>{t('medicines')}</b>
          <div style={{ marginTop: 8 }}>
            {meds.length === 0 && <div className="muted small">{t('empty')}</div>}
            {meds.map((m) => (
              <div className="item" key={m.id}>
                <span>{m.taken ? '✅' : '⏰'}</span>
                <span className="grow">
                  <b>{m.name}</b>
                  <div className="small muted">{m.time} · {m.note}</div>
                </span>
                <span className={'chip' + (m.taken ? ' done' : '')}>{t('taken')}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="card">
          <b>{t('emergency')}</b>
          <p className="small muted" style={{ marginTop: 6 }}>
            {t('fall_sub')}
          </p>
          <button className="btn ghost wide" onClick={onTestThud}>{t('test_thud')}</button>
        </div>
      </div>
    </div>
  )
}
