/**
 * D5 — the family monitor.
 *
 * It mirrors the elder's app A-to-Z: same profile, same medicines, same
 * activity feed, same incidents, same emergency card. The one deliberate
 * difference is the design's rule — the elder's SOS button becomes the
 * family's Alerts bell. Nothing rings here; it tells.
 */
import { useEffect, useRef, useState } from 'react'
import { VITAL_LABEL_KEY } from '../lib/i18n'

const MOOD_ICON = { good: '🙂', ok: '😐', bad: '🤒', unknown: '💬' }
const BAND_CLASS = { normal: 'ok', elevated: 'attention', high: 'emergency',
  'very high': 'emergency', critical: 'emergency', low: 'attention' }

const SRC_ICON = {
  fall: '🚨', sos: '🚨', triage: '🩺', agent: '💬', note: '📝',
  system: '⚙️', checkin: '🙂', monitor: '👨‍👩‍👧', voice: '🎙️',
}

/** Relative time. Falls back to plain English where no `t` is in scope. */
export function agoText(ts, t) {
  const say = t || ((k, v) => {
    const n = (v && v.n) || 1
    return ({ ago_never: 'never', ago_now: 'just now',
              ago_min: `${n} min ago`, ago_h: `${n} h ago`,
              ago_d: `${n} d ago` })[k] || ''
  })
  if (!ts) return say('ago_never')
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts))
  if (s < 45) return say('ago_now')
  if (s < 3600) return say('ago_min', { n: Math.floor(s / 60) })
  if (s < 86400) return say('ago_h', { n: Math.floor(s / 3600) })
  return say('ago_d', { n: Math.floor(s / 86400) })
}

const clock = (ts, lang) => new Date(ts * 1000).toLocaleTimeString(lang,
  { hour: '2-digit', minute: '2-digit' })

const dayTime = (ts, lang) => new Date(ts * 1000).toLocaleString(lang,
  { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

export default function MonitorView({
  t, lang, data, onAsk, onOpenIncident, onAck, onCall, live,
}) {
  const [tab, setTab] = useState('today')
  const p = data?.profile || {}
  const s = data?.summary || {}
  const meds = data?.meds || []
  const notifs = data?.notifications || []
  const activity = data?.activity || []
  const incidents = data?.emergencies || []
  const alarm = data?.alarm
  const ack = data?.monitor || {}
  const checkins = data?.checkins || []
  const sehat = data?.sehat || null

  const ago = (ts) => agoText(ts, t)
  const open = incidents.filter((e) => e.status === 'open')
  const unread = data?.unread || 0
  const status = s.status || 'ok'
  const name = (p.name || '').split(' ')[0] || 'your elder'

  // A new unread alert lifts the bell tab into view on its own — the family
  // should not have to go looking during an emergency.
  const seenRef = useRef(unread)
  useEffect(() => {
    if (unread > seenRef.current) setTab('alerts')
    seenRef.current = unread
  }, [unread])

  // The bell is the family's SOS. It goes up for a fall or an open incident,
  // and for any unread alert the server itself marked urgent — which is what
  // a "she says she feels unwell" check-in becomes.
  const urgent = notifs.filter((n) => !n.read && n.kind === 'emergency')
  const bellRinging = urgent.length > 0
    || (status === 'emergency' && (unread > 0 || open.length > 0))

  const pill = {
    ok: ['🟢', t('status_ok'), 'var(--ok)'],
    attention: ['🟡', t('status_attention'), 'var(--warn)'],
    emergency: ['🔴', t('status_emergency'), 'var(--danger)'],
  }[status]

  return (
    <div className="wrap mon" style={{ paddingBottom: 90 }}>
      {/* ---------------- who we are watching ---------------- */}
      <div className="monhead">
        <div className="row" style={{ gap: 12, alignItems: 'flex-start' }}>
          <div className="avatar">{(p.name || 'S').slice(0, 1)}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="moname">
              {t('watching_over')}: <b>{p.name || '—'}</b>
              {p.age ? `, ${p.age}` : ''}
            </div>
            <div className="small muted monline">
              <span className={'pill ' + status}>
                {pill[0]} {pill[1]}
              </span>
              <span>· {t('last_seen')} {s.last_seen_ago || '—'}</span>
              <span>· {t('updated')} {ago(data?.generated_at)}</span>
              {live ? <span className="livedot">● {t('live')}</span> : null}
            </div>
          </div>
        </div>
      </div>

      {/* ---------------- the bell: only on a real emergency -------------- */}
      {bellRinging ? (
        <div className="alertbar" role="alert">
          <div className="row" style={{ gap: 12, alignItems: 'flex-start' }}>
            <div className="bell">🔔</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <b>
                {open.length
                  ? `${open[0].kind === 'sos' ? 'SOS' : t('fall')} — ${t('open_incident')}`
                  : urgent[0]?.title || notifs.find((n) => !n.read)?.title
                    || t('status_emergency')}
              </b>
              <div className="small">
                {open.length
                  ? `${dayTime(open[0].ts, lang)} · ${ago(open[0].ts)}`
                  : (urgent[0] || notifs.find((n) => !n.read))?.body || ''}
              </div>
              {open[0]?.hospitals?.length ? (
                <div className="small muted" style={{ marginTop: 4 }}>
                  🏥 {open[0].hospitals[0].name}
                  {open[0].hospitals[0].distance_m != null
                    ? ` · ${open[0].hospitals[0].distance_m} m` : ''}
                </div>
              ) : null}
            </div>
          </div>
          <div className="row" style={{ gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
            <a className="btn danger small" href="tel:112"
               style={{ textDecoration: 'none' }}>🚑 112</a>
            {open.length ? (
              <a className="btn small" href={open[0].calls?.family || '#'}
                 style={{ textDecoration: 'none' }}>
                📞 {t('call_now')}
              </a>
            ) : null}
            {open.length ? (
              <button className="btn ghost small"
                      onClick={() => onOpenIncident(open[0])}>
                {t('view_incident')}
              </button>
            ) : null}
            <button className="btn ok small" onClick={() => onAck()}>
              ✓ {t('ack')}
            </button>
          </div>
          {ack.last_ack ? (
            <div className="small muted" style={{ marginTop: 8 }}>
              ✓ {t('acked_by', { who: ack.acked_by || 'family' })} · {ago(ack.last_ack)}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* ---------------- ask bar ---------------- */}
      <div className="bar" onClick={() => onAsk('')}>
        <span style={{ fontSize: 18 }}>🔎</span>
        <input readOnly placeholder={t('ask_about', { name })} />
        <span className="chip">{t('send')}</span>
      </div>
      <div className="small muted" style={{ marginTop: 6 }}>
        {t('monitor_hint', { name })}
      </div>
      <div className="chips" style={{ marginTop: 10 }}>
        <button className="chip ask" onClick={() => onAsk(t('how_is_she'))}>
          🙂 {t('how_is_she')}
        </button>
        <button className="chip ask" onClick={() => onAsk(t('meds_q'))}>
          💊 {t('meds_q')}
        </button>
        <button className="chip ask" onClick={() => onAsk(t('any_alerts'))}>
          🔔 {t('any_alerts')}
        </button>
      </div>

      {/* ---------------- four numbers ---------------- */}
      <div className="grid four" style={{ marginTop: 14 }}>
        <div className="stat">
          <span className="n">{s.meds_taken ?? 0}<i>/{s.meds_total ?? 0}</i></span>
          <span className="l">{t('meds_today')}</span>
        </div>
        <div className={'stat' + (unread ? ' warn' : '')}>
          <span className="n">{unread}</span>
          <span className="l">{t('alerts')}</span>
        </div>
        <div className="stat">
          <span className="n">{s.events_today ?? 0}</span>
          <span className="l">{t('activity')}</span>
        </div>
        <div className={'stat' + (open.length ? ' bad' : '')}>
          <span className="n">{open.length}</span>
          <span className="l">{t('incidents')}</span>
        </div>
      </div>

      {/* ---------------- tabs ---------------- */}
      <div className="tabs" style={{ marginTop: 18 }}>
        {[['today', '📋 ' + t('today')], ['alerts', '🔔 ' + t('alerts') +
          (unread ? ` (${unread})` : '')],
         ['activity', '🕘 ' + t('activity')],
         ['incidents', '🚨 ' + t('incidents')]].map(([k, label]) => (
          <button key={k} className={'tab' + (tab === k ? ' on' : '')}
                  onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>

      {tab === 'today' && (
        <>
          <div className="card" style={{ marginTop: 12 }}>
            <b>{t('today')} — {s.date}</b>
            <div style={{ marginTop: 10 }}>
              {(s.highlights || []).map((h, i) => (
                <div className="pbul" key={i}><span>✅</span><span>{h}</span></div>
              ))}
              {!s.highlights?.length && (
                <div className="small muted">{t('nothing_today')}</div>
              )}
            </div>
            {s.concerns?.length ? (
              <>
                <div className="secT">{t('concerns')}</div>
                {s.concerns.map((c, i) => (
                  <div className="pbul warn" key={i}>
                    <span>⚠️</span><span>{c}</span>
                  </div>
                ))}
              </>
            ) : null}
          </div>

          {/* D6 — what she actually said today */}
          <div className="card" style={{ marginTop: 12 }}>
            <div className="row">
              <b style={{ flex: 1 }}>🙂 {t('checkin_today')}</b>
              {s.mood ? (
                <span className={'pill ' + (s.mood === 'bad' ? 'emergency'
                  : s.mood === 'ok' ? 'attention' : 'ok')}>
                  {MOOD_ICON[s.mood]} {t('mood_' + s.mood)}
                </span>
              ) : (
                <span className="small muted">{t('checkin_none')}</span>
              )}
            </div>
            {checkins.length === 0 && (
              <div className="small muted" style={{ marginTop: 8 }}>
                {t('checkin_none')}
              </div>
            )}
            {checkins.slice(0, 4).map((c) => (
              <div className="ckrow" key={c.id}>
                <span>{MOOD_ICON[c.mood] || (c.status === 'missed' ? '🔕' : '💬')}</span>
                <span className="grow small">
                  <b>{c.kind === 'evening' ? t('checkin_evening')
                    : t('checkin_morning')}</b>
                  <div className="muted">
                    {c.status === 'missed'
                      ? t('checkin_missed', { kind: c.kind })
                      : (c.summary || (c.mood ? t('mood_' + c.mood) : ''))}
                    {c.flags?.length ? ` · ${c.flags.join(', ')}` : ''}
                  </div>
                </span>
                <span className="small muted">{clock(c.ts, lang)}</span>
              </div>
            ))}
          </div>

          {/* D7 — the body numbers the elder sees on her Sehat Board */}
          {sehat ? (
            <div className="card" style={{ marginTop: 12 }}>
              <div className="row" style={{ flexWrap: 'wrap' }}>
                <b style={{ flex: 1 }}>🩺 {t('sehat')}</b>
                {sehat.bmi ? (
                  <span className="chip">
                    BMI {sehat.bmi.bmi} · {t('b_' + sehat.bmi.band)}
                  </span>
                ) : null}
                {sehat.board?.streak ? (
                  <span className="chip">
                    🔥 {t('streak', { n: sehat.board.streak })}
                  </span>
                ) : null}
                <span className="chip">
                  {t('weekly_pts', { a: sehat.board?.total ?? 0,
                    b: sehat.board?.target ?? 300 })}
                </span>
              </div>
              <div className="hgrid" style={{ marginTop: 10 }}>
                {Object.entries(sehat.vitals_latest || {}).map(([k, v]) => (
                  <div className="item" key={k}>
                    <span className="grow small">{v.icon || t(VITAL_LABEL_KEY[k] || k)}</span>
                    <b>{Math.round(v.value * 10) / 10}</b>
                    <span className={'pill ' + (BAND_CLASS[v.band] || 'ok')}>
                      {t('band_' + String(v.band).replace(' ', '_'))}
                    </span>
                  </div>
                ))}
                {!Object.keys(sehat.vitals_latest || {}).length && (
                  <div className="small muted">{t('no_readings')}</div>
                )}
              </div>
              {sehat.alerts?.length ? (
                <div className="small" style={{ marginTop: 8,
                  color: 'var(--warn)' }}>
                  ⚠️ {sehat.alerts.length} reading(s) outside the usual range
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="grid two" style={{ marginTop: 12 }}>
            <div className="card">
              <b>💊 {t('meds_today')}</b>
              <div className="small muted">
                {t('of_taken', { a: s.meds_taken ?? 0, b: s.meds_total ?? 0 })}
                {s.adherence != null ? ` · ${s.adherence}%` : ''}
              </div>
              <div style={{ marginTop: 8 }}>
                {meds.length === 0 && (
                  <div className="small muted">{t('no_meds_logged')}</div>
                )}
                {meds.map((m) => (
                  <div className="item" key={m.id}>
                    <span>{m.taken ? '✅' : '⏰'}</span>
                    <span className="grow">
                      <b>{m.name}</b>
                      <div className="small muted">{m.time}{m.note ? ` · ${m.note}` : ''}</div>
                    </span>
                    <span className={'chip' + (m.taken ? ' done' : '')}>
                      {m.taken ? t('taken') : t('pending')}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className="card">
              <b>🙂 {t('checkins')}</b>
              <div style={{ marginTop: 8 }}>
                {!s.checkins?.length && (
                  <div className="small muted">{t('nothing_today')}</div>
                )}
                {(s.checkins || []).map((c, i) => (
                  <div className="item" key={i}>
                    <span>{SRC_ICON[c.source] || '•'}</span>
                    <span className="grow small">{c.text}</span>
                    <span className="small muted">{clock(c.ts, lang)}</span>
                  </div>
                ))}
              </div>
              <div className="secT">{t('ecard')}</div>
              <div className="small muted">
                {(data?.card?.conditions || []).join(', ') || '—'}
                {' · '}
                {data?.card?.blood_group || '—'}
              </div>
            </div>
          </div>
        </>
      )}

      {tab === 'alerts' && (
        <div style={{ marginTop: 12 }}>
          {notifs.length === 0 && <div className="muted small">{t('empty')}</div>}
          {notifs.map((n) => (
            <div className={'nrow' + (n.kind === 'emergency' ? ' urgent' : '')}
                 key={n.id}>
              {!n.read ? <span className="uni" /> : <span className="uni read" />}
              <span className="ni">{n.kind === 'emergency' ? '🚨' : '🔔'}</span>
              <span className="mi">
                <b>{n.title}</b>
                <div className="small muted">{n.body}</div>
                <div className="small muted">{ago(n.ts)}</div>
              </span>
            </div>
          ))}
        </div>
      )}

      {tab === 'activity' && (
        <div className="card" style={{ marginTop: 12 }}>
          <b>🕘 {t('activity')}</b>
          <div style={{ marginTop: 8 }}>
            {activity.length === 0 && (
              <div className="small muted">{t('empty')}</div>
            )}
            {activity.map((a) => (
              <div className="item" key={a.id}>
                <span>{SRC_ICON[a.source] || '•'}</span>
                <span className="grow small">{a.text}</span>
                <span className="chip">{a.source}</span>
                <span className="small muted">{dayTime(a.ts)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'incidents' && (
        <div style={{ marginTop: 12 }}>
          {incidents.length === 0 && (
            <div className="muted small">{t('empty')}</div>
          )}
          {incidents.map((e) => (
            <div className={'nrow' + (e.status === 'open' ? ' urgent' : '')}
                 key={e.id}>
              <span className="ni">{e.kind === 'sos' ? '🆘' : '🚨'}</span>
              <span className="mi">
                <b>
                  {e.kind === 'sos' ? 'SOS' : t('fall')} · {t('severity')} {e.severity}/10
                </b>
                <div className="small muted">{dayTime(e.ts, lang)} · {ago(e.ts)}</div>
                <div className="small muted">
                  {e.hospitals?.[0]?.name
                    ? `🏥 ${e.hospitals[0].name}` : ''}
                  {e.ack_by ? ` · ✓ ${t('acked_by', { who: e.ack_by })}` : ''}
                </div>
              </span>
              <span className="chip">{e.status}</span>
              <button className="btn ghost small"
                      onClick={() => onOpenIncident(e)}>{t('view_incident')}</button>
            </div>
          ))}
        </div>
      )}

      {alarm?.status === 'ringing' && (
        <div className="card" style={{ marginTop: 12, borderColor: 'var(--warn)' }}>
          <b>⏳ {t('alarm_on_screen')}</b>
          <div className="small muted" style={{ marginTop: 4 }}>
            {alarm.kind === 'sos' ? 'SOS' : t('fall')}
            {alarm.confidence != null
              ? ` · ${t('confidence')} ${alarm.confidence}` : ''}
            {' · '}{t('started')} {ago(alarm.started)}
            {alarm.grace ? ` · ${t('s_to_answer', { n: alarm.grace })}` : ''}
          </div>
        </div>
      )}
    </div>
  )
}
