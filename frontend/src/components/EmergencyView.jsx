/**
 * D4 — what happens after "no answer".
 * One screen with everything a rescuer needs: the timeline of the event,
 * who to call (real tel: links that dial on a phone), the nearest hospitals
 * with distance + directions, and the Emergency Card.
 */
export default function EmergencyView({ lang, rec, t, onCall, onClose, onPrint }) {
  if (!rec) return null
  const card = rec.card || {}
  const hs = rec.hospitals || []
  const stageIcon = { detected: '🎧', alarm: '🔔', escalated: '🚨', called: '📞',
                      closed: '✅' }

  const fmt = (ts) => new Date(ts * 1000).toLocaleTimeString([], {
    hour: '2-digit', minute: '2-digit', second: '2-digit' })

  const ago = (ts) => {
    const s = Math.max(0, Math.floor(Date.now() / 1000 - ts))
    if (s < 45) return t('ago_now')
    if (s < 3600) return t('ago_min', { n: Math.floor(s / 60) })
    if (s < 86400) return t('ago_h', { n: Math.floor(s / 3600) })
    return t('ago_d', { n: Math.floor(s / 86400) })
  }

  const callBtn = (href, label, kind = '') => (
    <a key={label} className={'btn ' + (kind || 'ghost')} href={href}
       style={{ display: 'block', textAlign: 'center', textDecoration: 'none' }}>
      {label}
    </a>
  )

  return (
    <div className="wrap" style={{ paddingBottom: 40 }}>
      <div className="card" style={rec.kind === 'card'
        ? undefined : { borderColor: 'var(--danger)' }}>
        <div className="row">
          <span style={{ fontSize: 30 }}>{rec.kind === 'card' ? '🪪' : '🚨'}</span>
          <div style={{ flex: 1 }}>
            <b style={{ fontSize: 17 }}>
              {rec.kind === 'card'
                ? `🪪 ${t('ecard')}`
                : `${rec.kind === 'sos' ? 'SOS' : t('fall')} — ${t('emergency')}`}
            </b>
            <div className="small muted">
              {rec.kind === 'card'
                ? t('ecard_ready')
                : (<>{new Date(rec.ts * 1000).toLocaleString(lang)}
                    {rec.confidence != null
                      ? ` · ${t('confidence')} ${rec.confidence}` : ''}
                    {rec.source ? ` · ${rec.source}` : ''}</>)}
            </div>
          </div>
          <button className="btn ghost small" onClick={onClose}>✕</button>
        </div>
        {/* D5 — closes the loop: the family saw the bell on the monitor */}
        {rec.kind !== 'card' && rec.ack_by ? (
          <div className="small" style={{
            marginTop: 10, padding: '8px 10px', borderRadius: 10,
            border: '1px solid var(--ok)', color: 'var(--ok)',
          }}>
            ✓ {rec.ack_by} has seen this on the family monitor
            {rec.ack_at ? ` · ${rec.ack_at ? ago(rec.ack_at) : ''}` : ''}
            {' — '}help is aware.
          </div>
        ) : null}
      </div>

      <div className="grid two" style={{ marginTop: 12 }}>
        {/* ---------------- calls ---------------- */}
        <div className="card">
          <b>📞 {t('sos')}</b>
          <div className="col" style={{ marginTop: 10 }}>
            {rec.calls?.family
              ? callBtn(rec.calls.family,
                  `👨‍👩‍👧 ${rec.contact?.name || t('call_family')} — ${rec.contact?.phone || ''}`, '')
              : <div className="small muted">{rec.contact?.raw || t('no_family_number')}</div>}
            <a className="btn danger" href={rec.calls?.ambulance || 'tel:112'}
               style={{ display: 'block', textAlign: 'center', textDecoration: 'none' }}>
              🚑 {t('ambulance')} — 112
            </a>
            {rec.calls?.doctor ? callBtn(rec.calls.doctor, '🩺 ' + t('doctor'), 'ghost') : null}
            <button className="btn ghost"
                    onClick={() => onCall('family')}>{t('log_call')}</button>
          </div>
        </div>

        {/* ---------------- nearest hospitals ---------------- */}
        <div className="card">
          <b>🏥 {t('nearest_hospitals')}</b>
          <div style={{ marginTop: 8 }}>
            {hs.length === 0 && <div className="muted small">{t('empty')}</div>}
            {hs.map((h) => (
              <div className="item" key={h.id}>
                <span className="grow">
                  <b>{h.name}</b>
                  <div className="small muted">
                    {h.distance_m != null ? `${h.distance_m} m` : '—'}
                    {h.emergency ? ' · ' + t('emergency_ward') : ''}
                    {h.source === 'offline-list' ? ' · ' + t('offline_list') : ''}
                  </div>
                </span>
                {h.phone ? (
                  <a className="chip" href={`tel:${h.phone}`}>☎ {h.phone}</a>
                ) : null}
                {h.map ? (
                  <a className="chip" href={h.map} target="_blank" rel="noreferrer">
                    {t('directions')} ↗
                  </a>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ---------------- emergency card ---------------- */}
      <div className="card" style={{ marginTop: 12 }} id="ecard">
        <div className="row">
          <b style={{ flex: 1 }}>🪪 {t('ecard')}</b>
          <button className="btn ghost small" onClick={onPrint}>🖨 {t('print')}</button>
        </div>
        <div className="grid two" style={{ marginTop: 10 }}>
          <div>
            <div className="item">
              <span className="grow muted small">{t('card_name')}</span><b>{card.name || '—'}</b>
            </div>
            <div className="item">
              <span className="grow muted small">{t('card_age_gender')}</span>
              <b>{card.age || '—'} · {card.gender || '—'}</b>
            </div>
            <div className="item">
              <span className="grow muted small">{t('blood_group')}</span>
              <b>{card.blood_group || '—'}</b>
            </div>
            <div className="item">
              <span className="grow muted small">{t('conditions')}</span>
              <span>{(card.conditions || []).join(', ') || '—'}</span>
            </div>
            <div className="item">
              <span className="grow muted small">{t('card_allergies')}</span>
              <span>{(card.allergies || []).join(', ') || '—'}</span>
            </div>
          </div>
          <div>
            <div className="small muted">{t('card_meds')}</div>
            {(card.medicines || []).length === 0 && (
              <div className="small muted">—</div>
            )}
            {(card.medicines || []).map((m, i) => (
              <div className="item" key={i}>
                <span className="grow small">{m.name}</span>
                <span className="chip">{m.time}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="small muted" style={{ marginTop: 10 }}>{card.note}</div>
      </div>

      {/* ---------------- timeline ---------------- */}
      <div className="card" style={{ marginTop: 12 }}>
        <b>🕘 {t('timeline')}</b>
        <div style={{ marginTop: 8 }}>
          {(rec.timeline || []).map((e, i) => (
            <div className="item" key={i}>
              <span style={{ width: 22 }}>{stageIcon[e.stage] || '•'}</span>
              <span className="grow small">{e.text}</span>
              <span className="small muted">{fmt(e.ts)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
