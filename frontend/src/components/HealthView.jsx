/**
 * D7 — Sehat Board.
 *
 * The elder's own health page: her body (editable, BMI worked out for her),
 * today's readings, and her week scored day by day.
 *
 * Two deliberate choices:
 *  - The board ranks HER OWN seven days against each other. There are no
 *    other users in this build, and a fake peer leaderboard is the kind of
 *    number a family might act on.
 *  - The six days of history this build ships are labelled as sample data,
 *    in the UI, in plain words.
 */
import { useEffect, useMemo, useState } from 'react'
import { VITAL_LABEL_KEY } from '../lib/i18n'
import { api } from '../lib/api'

/** key -> icon. Labels are translated at render time, never here. */
const VITALS = [
  ['bp_sys', '🩺'], ['bp_dia', '🩺'], ['sugar', '🍬'],
  ['pulse', '❤️'], ['spo2', '🫁'],
]
const BAND_CLASS = {
  normal: 'ok', elevated: 'attention', high: 'emergency',
  'very high': 'emergency', critical: 'emergency', low: 'attention',
}

/** Tiny inline SVG sparkline — no chart library, works offline. */
function Spark({ pts, band }) {
  if (!pts || pts.length < 2) return null
  const w = 116, h = 30, pad = 3
  const vs = pts.map((p) => p.v)
  const lo = Math.min(...vs), hi = Math.max(...vs)
  const span = hi - lo || 1
  const x = (i) => pad + (i * (w - pad * 2)) / (pts.length - 1)
  const y = (v) => h - pad - ((v - lo) / span) * (h - pad * 2)
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ')
  const colour = band && band !== 'normal' ? 'var(--warn)' : 'var(--ok)'
  return (
    <svg width={w} height={h} className="spark" aria-hidden="true">
      <path d={d} fill="none" stroke={colour} strokeWidth="1.8"
            strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(pts.length - 1)} cy={y(vs[vs.length - 1])} r="2.6"
              fill={colour} />
    </svg>
  )
}

export default function HealthView({ t, state, onToggleMed, onDeleteMed,
                                      onAddMed, board, setBoard }) {
  const p = state?.profile || {}
  const [draft, setDraft] = useState(null)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState(null)
  const [tab, setTab] = useState('board')

  // editable body fields — local until saved
  const d = draft || {}
  const val = (k, fb) => (d[k] !== undefined ? d[k] : (p[k] ?? fb))

  const b = board?.bmi
  const latest = board?.vitals_latest || {}
  const series = board?.vitals_series || {}
  const wk = board?.board

  const bmiLive = useMemo(() => {
    const w = parseFloat(val('weight_kg', ''))
    const h = parseFloat(val('height_cm', ''))
    if (!w || !h) return null
    const v = w / (h / 100) ** 2
    const band = v < 18.5 ? 'underweight' : v < 23 ? 'normal'
      : v < 25 ? 'overweight' : 'obese'
    return { bmi: Math.round(v * 10) / 10, band }
  }, [p.weight_kg, p.height_cm, d.weight_kg, d.height_cm])   // eslint-disable-line

  const live = bmiLive || b

  useEffect(() => {
    if (!board) api.sehat().then(setBoard).catch(() => {})
  }, [board, setBoard])

  const edit = (k, v) => setDraft((x) => ({ ...(x || {}), [k]: v }))
  const dirty = draft && Object.keys(draft).length > 0

  async function save() {
    setSaving(true)
    try {
      const patch = { ...draft }
      if (patch.conditions_text !== undefined) {
        patch.conditions = String(patch.conditions_text)
          .split(',').map((s) => s.trim()).filter(Boolean)
        delete patch.conditions_text
      }
      await api.saveProfile(patch)
      setDraft(null)
      const fresh = await api.sehat()
      setBoard(fresh)
    } catch (e) { /* offline */ }
    setSaving(false)
  }

  async function logVitals(e) {
    e.preventDefault()
    const payload = {}
    for (const k of ['bp_sys', 'bp_dia', 'sugar', 'pulse', 'spo2']) {
      const v = parseFloat(form?.[k])
      if (!Number.isNaN(v)) payload[k] = v
    }
    if (!Object.keys(payload).length) return
    await api.logVitals(payload)
    setForm(null)
    setBoard(await api.sehat())
  }

  const vitalFields = VITALS.map(([k]) => [k, t(VITAL_LABEL_KEY[k])])
  const ptsRules = [
    ['🙂', t('p_checkin'), 8], ['💊', t('p_med'), 10],
    ['🚶', t('p_activity'), 5], ['🩺', t('p_vitals'), 4],
    ['💬', t('p_chat'), 3], ['⚠️', t('p_missed'), -5],
  ]

  return (
    <div className="wrap sehat" style={{ paddingBottom: 90 }}>
      <div className="hero">
        <div>
          <div className="big">🩺 {t('sehat')}</div>
          <div className="muted small">{t('sehat_sub')}</div>
        </div>
      </div>

      <div className="tabs">
        {[['board', '📊 ' + t('weekly_board')], ['you', '🧍 ' + t('you_editable')],
          ['vitals', '🩺 ' + t('vitals')]].map(([k, label]) => (
          <button key={k} className={'tab' + (tab === k ? ' on' : '')}
                  onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>

      {/* ------------------------------------------------ 1 · the week ---- */}
      {tab === 'board' && (
        <>
          <div className="grid four" style={{ marginTop: 12 }}>
            {VITALS.map(([k, icon]) => {
              const v = latest[k]
              return (
                <div className="stat" key={k}>
                  <span className="n" style={{ fontSize: 21 }}>
                    {v ? Math.round(v.value * 10) / 10 : '—'}
                  </span>
                  <span className="l">{icon} {t(VITAL_LABEL_KEY[k])}</span>
                  {v ? (
                    <span className={'pill ' + (BAND_CLASS[v.band] || 'ok')}>
                      {t('band_' + v.band.replace(' ', '_'))}
                    </span>
                  ) : (
                    <span className="small muted">{t('no_readings')}</span>
                  )}
                </div>
              )
            })}
          </div>

          {wk ? (
            <div className="card" style={{ marginTop: 12 }}>
              <div className="row" style={{ flexWrap: 'wrap' }}>
                <b style={{ flex: 1 }}>📊 {t('weekly_board')}</b>
                {wk.streak > 0 ? (
                  <span className="chip">🔥 {t('streak', { n: wk.streak })}</span>
                ) : null}
                <span className="chip">
                  {t('weekly_pts', { a: wk.total, b: wk.target })}
                </span>
                {wk.badge ? (
                  <span className="chip done">
                    {t('badge_earned', { b: t(wk.badge) })}
                  </span>
                ) : null}
              </div>
              <div className="prog" style={{ marginTop: 10 }}>
                <div style={{ width: `${wk.pct}%` }} />
              </div>
              <div className="small muted" style={{ marginTop: 6 }}>
                {wk.badge
                  ? t('badge_earned', { b: t(wk.badge) })
                  : t('more_pts', { n: Math.max(0, wk.target - wk.total) })}
              </div>

              <table className="lb" style={{ marginTop: 12 }}>
                <thead>
                  <tr><th>{t('pos')}</th><th>{t('day')}</th>
                      <th>{t('date')}</th><th>{t('points')}</th></tr>
                </thead>
                <tbody>
                  {wk.days.map((row) => (
                    <tr key={row.date} className={row.today ? 'live' : ''}>
                      <td className="pos">
                        {row.rank === 1 && row.points > 0 ? '🥇 ' : ''}#{row.rank}
                      </td>
                      <td>
                        {row.today ? <b>{t('today_live')}</b>
                          : (row.dow ? t('dow_' + row.dow) : row.day)}
                      </td>
                      <td className="muted">
                        {row.dow ? `${t('dow_' + row.dow)} ${row.date.slice(8)}`
                          : row.short}
                      </td>
                      <td className="pts">
                        {row.today ? t('pts_so_far', { n: row.points })
                          : row.points}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="small muted" style={{ marginTop: 8 }}>
                {t('own_week')}
              </div>
              {wk.seeded ? (
                <div className="small muted" style={{ marginTop: 4 }}>
                  {t('sample_note')}
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="card" style={{ marginTop: 12 }}>
            <b>{t('how_points')}</b>
            {ptsRules.map(([icon, label, n]) => (
              <div className="pbul" key={label}>
                <span>{icon}</span><span style={{ flex: 1 }}>{label}</span>
                <b style={{ color: n < 0 ? 'var(--danger)' : 'var(--ok)' }}>
                  {n > 0 ? '+' : ''}{n}
                </b>
              </div>
            ))}
            <div className="small muted" style={{ marginTop: 8 }}>
              {t('consistency')}
            </div>
          </div>
        </>
      )}

      {/* -------------------------------------------------- 2 · you ------- */}
      {tab === 'you' && (
        <div className="card" style={{ marginTop: 12 }}>
          <div className="hgrid">
            <div>
              <span className="lbl2">{t('gender')}</span>
              <div className="chips">
                {[['male', t('male')], ['female', t('female')],
                  ['other', t('other_g')]].map(([g, label]) => (
                  <button key={g}
                          className={'chip ask' + (val('gender', '') === g ? ' on' : '')}
                          onClick={() => edit('gender', g)}>{label}</button>
                ))}
              </div>
            </div>
            <div>
              <span className="lbl2">{t('age')} & {t('dob')}</span>
              <div style={{ fontSize: 16, fontWeight: 700 }}>
                {t('age')}: {val('age', '')}
              </div>
              <input className="inp" type="date" value={val('dob', '') || ''}
                     onChange={(e) => edit('dob', e.target.value)}
                     style={{ marginTop: 6 }} />
            </div>
          </div>

          <hr className="hr" />
          <span className="lbl2">{t('conditions')}</span>
          <input className="inp"
                 defaultValue={(p.conditions || []).join(', ')}
                 onChange={(e) => edit('conditions_text', e.target.value)} />

          <hr className="hr" />
          <div className="hgrid three">
            <div>
              <span className="lbl2">{t('weight')}</span>
              <input className="inp" type="number" value={val('weight_kg', '')}
                     onChange={(e) => edit('weight_kg', e.target.value)} />
            </div>
            <div>
              <span className="lbl2">{t('height')}</span>
              <input className="inp" type="number" value={val('height_cm', '')}
                     onChange={(e) => edit('height_cm', e.target.value)} />
            </div>
            <div>
              <span className="lbl2">{t('blood_group')}</span>
              <select className="inp" value={val('blood_group', 'O+')}
                      onChange={(e) => edit('blood_group', e.target.value)}>
                {['O+', 'O−', 'A+', 'A−', 'B+', 'B−', 'AB+', 'AB−'].map((g) => (
                  <option key={g} value={g}>{g}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="hgrid2" style={{ marginTop: 14 }}>
            <div style={{ display: 'flex', alignItems: 'flex-end' }}>
              <button className={'btn' + (dirty ? '' : ' ghost')} disabled={!dirty}
                      onClick={save}>
                {saving ? '…' : t('save_changes')}
              </button>
            </div>
            <div className="bmibox">
              <span className="lbl2">{t('bmi_auto')}</span>
              <div className="n">{live ? live.bmi : '—'}</div>
              {live ? (
                <span className={'pill ' + (live.band === 'normal' ? 'ok'
                  : live.band === 'underweight' ? 'attention' : 'emergency')}>
                  {t('b_' + live.band)}
                </span>
              ) : null}
            </div>
          </div>
          {dirty ? (
            <div className="small muted" style={{ marginTop: 8 }}>
              ✏️ {t('unsaved')}
            </div>
          ) : null}
        </div>
      )}

      {/* ----------------------------------------------- 3 · vitals ------- */}
      {tab === 'vitals' && (
        <>
          <div className="card" style={{ marginTop: 12 }}>
            <div className="row">
              <b style={{ flex: 1 }}>🩺 {t('vitals')}</b>
              <button className="btn small"
                      onClick={() => setForm(form ? null : {})}>
                {form ? t('cancel') : '+ ' + t('log_vitals')}
              </button>
            </div>

            {form ? (
              <form onSubmit={logVitals} style={{ marginTop: 10 }}>
                <div className="hgrid three">
                  {vitalFields.map(([k, label]) => (
                    <div key={k}>
                      <span className="lbl2">{label}</span>
                      <input className="inp" type="number" step="0.1"
                             value={form[k] ?? ''}
                             onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))} />
                    </div>
                  ))}
                </div>
                <button className="btn" style={{ marginTop: 12 }} type="submit">
                  {t('log_vitals')}
                </button>
              </form>
            ) : null}

            <div style={{ marginTop: 10 }}>
              {Object.keys(latest).length === 0 && (
                <div className="small muted">{t('no_readings')}</div>
              )}
              {Object.keys(series).map((k) => {
                const v = latest[k]
                return (
                  <div className="ckrow" key={k}>
                    <span style={{ width: 116 }}>
                      <Spark pts={series[k]} band={v?.band} />
                    </span>
                    <span className="grow">
                      <b>{t(VITAL_LABEL_KEY[k])}</b>
                      <div className="small muted">
                        {v ? `${Math.round(v.value * 10) / 10} · ${v.ago}` : ''}
                      </div>
                    </span>
                    {v ? (
                      <span className={'pill ' + (BAND_CLASS[v.band] || 'ok')}>
                        {t('band_' + v.band.replace(' ', '_'))}
                      </span>
                    ) : null}
                  </div>
                )
              })}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
