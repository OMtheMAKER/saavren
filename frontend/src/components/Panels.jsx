import { useEffect, useState } from 'react'
import { LANGS } from '../lib/i18n'
import { api } from '../lib/api'

export function Panel({ title, onClose, children }) {
  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="drawer">
        <header>
          <b style={{ flex: 1 }}>{title}</b>
          <button className="iconbtn" onClick={onClose}>✕</button>
        </header>
        <div className="body">{children}</div>
      </aside>
    </>
  )
}

export function ActivityPanel({ t, lang, state, onRead, onClose,
  routine, onToggleAlarm, board }) {
  const acts = state?.activity || []
  const rows = (routine && routine.items) || []
  // the badge is a UI label, not data: translate it, but never show a raw
  // key if a source turns up that has no string yet
  const srcLabel = (src) => {
    const out = t('src_' + src)
    return out.startsWith('src_') ? src : out
  }
  // the board already ranks the week; show it best-first
  const week = [...((board && board.days) || [])]
    .sort((a, b) => (a.rank || 0) - (b.rank || 0))

  return (
    <Panel title={t('activity')} onClose={onClose}>

      {/* ---- today's routine, with an alarm on every row ---- */}
      <label className="small muted">{t('routine')}</label>
      <div style={{ marginBottom: 14 }}>
        {rows.length === 0 && <div className="muted small">{t('routine_empty')}</div>}
        {rows.map((r) => (
          <div className="item" key={r.key}>
            <span className="small muted" style={{ width: 46, flex: 'none' }}>
              {r.time || '\u2014'}
            </span>
            <span className="grow small">
              {/* medicine names are the elder's own data; the built-in rows
                  arrive as i18n keys so they follow the language */}
              {r.kind === 'med' ? r.label : t(r.label)}
              {r.done
                ? <span className="chip done" style={{ marginLeft: 6 }}>{t('taken')}</span>
                : null}
            </span>
            <button className="iconbtn"
                    title={r.alarm ? t('alarm_on') : t('alarm_off')}
                    onClick={() => onToggleAlarm(r.key, !r.alarm)}>
              {r.alarm ? '\uD83D\uDD14' : '\uD83D\uDD15'}
            </button>
          </div>
        ))}
      </div>

      {/* ---- this week, ranked ---- */}
      <label className="small muted">{t('weekly_ranking')}</label>
      <div style={{ marginBottom: 14 }}>
        {week.length === 0 && <div className="muted small">{t('empty')}</div>}
        {week.map((d) => (
          <div className="item" key={d.date}>
            <span className="chip">{d.rank}</span>
            <span className="grow small">
              {d.today ? <b>{t('today_live')}</b> : t('dow_' + d.dow)}
            </span>
            <span className="small muted">{t('pts_so_far', { n: d.points })}</span>
          </div>
        ))}
      </div>

      {/* ---- the feed itself: time-stamped, source-badged ---- */}
      <label className="small muted">{t('activity')}</label>
      <button className="btn ghost wide small" onClick={onRead}>{t('mark_read')}</button>
      <div style={{ marginTop: 8 }}>
        {acts.length === 0 && <div className="muted small">{t('empty')}</div>}
        {acts.map((a) => (
          <div className="item" key={a.id}>
            <span className="chip">{srcLabel(a.source)}</span>
            <span className="grow small">{a.text}</span>
            <span className="small muted">
              {new Date(a.ts * 1000).toLocaleString(lang, {
                day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>
        ))}
      </div>
    </Panel>
  )
}

export function NotifyPanel({ t, lang, state, onRead, onClose }) {
  const ns = state?.notifications || []
  return (
    <Panel title={t('notifications')} onClose={onClose}>
      <button className="btn ghost wide small" onClick={onRead}>{t('mark_read')}</button>
      <div style={{ marginTop: 10 }}>
        {ns.length === 0 && <div className="muted small">{t('empty')}</div>}
        {ns.map((n) => (
          <div className="card" key={n.id} style={{ marginBottom: 8,
            borderColor: n.kind === 'emergency' ? 'var(--danger)' : undefined }}>
            <b>{n.title}{n.kind === 'emergency' ? ' 🚨' : ''}</b>
            <div className="small muted" style={{ marginTop: 4 }}>{n.body}</div>
            <div className="small muted" style={{ marginTop: 6 }}>
              {new Date(n.ts * 1000).toLocaleString(lang)}
            </div>
          </div>
        ))}
      </div>
    </Panel>
  )
}

/** Error codes the account endpoints return. The server sends a code, never
    display text, so the message follows the chosen language. */
const AUTH_ERRORS = [
  'auth_bad_login', 'auth_username_taken', 'auth_short_password',
  'auth_bad_username', 'auth_bad_role', 'auth_no_name', 'auth_mismatch',
]

const authMessage = (t, code) =>
  (AUTH_ERRORS.indexOf(code) >= 0 ? t(code) : code)

/**
 * Accounts are optional — the app is fully usable without one. Signing in
 * puts your name on the family's alerts and opens your own screen first.
 */
export function AccountSection({ t, user, onAuthed, onSignOut }) {
  const [mode, setMode] = useState('signin')   // signin | signup
  const [name, setName] = useState('')
  const [username, setUsername] = useState('')
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [role, setRole] = useState('elder')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => { setErr('') }, [mode, user])

  async function submit(e) {
    e.preventDefault()
    setErr('')
    if (mode === 'signup' && pw !== pw2) { setErr(t('auth_mismatch')); return }
    setBusy(true)
    try {
      const out = mode === 'signup'
        ? await api.signup(name, username, pw, role)
        : await api.login(username, pw)
      onAuthed(out.user, out.token)
      setName(''); setUsername(''); setPw(''); setPw2('')
    } catch (ex) {
      setErr(authMessage(t, ex.message))
    } finally {
      setBusy(false)
    }
  }

  if (user) {
    return (
      <div className="col">
        <label className="small muted">{t('account')}</label>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <div>
            <b>{user.name}</b>
            <div className="small muted">
              {t('signed_in_as', { n: user.username })}
              {' · '}
              {user.role === 'family' ? t('role_family') : t('role_elder')}
            </div>
          </div>
          <button className="btn ghost small" onClick={onSignOut}
                  disabled={busy}>{t('sign_out')}</button>
        </div>
      </div>
    )
  }

  return (
    <div className="col">
      <label className="small muted">
        {t('account')}
        <span className="chip" style={{ marginLeft: 6 }}>{t('auth_optional')}</span>
      </label>
      <div className="small muted">{t('account_hint')}</div>

      <form onSubmit={submit} className="col">
        {mode === 'signup' ? (
          <>
            <input className="inp" value={name} onChange={(e) => setName(e.target.value)}
                   placeholder={t('auth_name')} autoComplete="name" required />
            <select className="sel" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="elder">{t('role_elder')}</option>
              <option value="family">{t('role_family')}</option>
            </select>
          </>
        ) : null}

        <input className="inp" value={username} onChange={(e) => setUsername(e.target.value)}
               placeholder={t('auth_username')} autoComplete="username" required />
        <input className="inp" type="password" value={pw}
               onChange={(e) => setPw(e.target.value)}
               placeholder={t('auth_password')}
               autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
               required />

        {mode === 'signup' ? (
          <>
            <input className="inp" type="password" value={pw2}
                   onChange={(e) => setPw2(e.target.value)}
                   placeholder={t('auth_confirm')} autoComplete="new-password" required />
            <div className="small muted">{t('auth_password_rule')}</div>
            <div className="small muted">{t('auth_username_rule')}</div>
          </>
        ) : null}

        {err ? <div className="small" style={{ color: 'var(--danger)' }}>{err}</div> : null}

        <button className="btn" type="submit" disabled={busy}>
          {mode === 'signup' ? t('create_account') : t('sign_in')}
        </button>
      </form>

      <button className="btn ghost small"
              onClick={() => setMode(mode === 'signup' ? 'signin' : 'signup')}>
        {mode === 'signup' ? t('auth_toggle_signin') : t('auth_toggle_signup')}
      </button>
    </div>
  )
}

/**
 * Check-in times. Each edit saves on the spot — a schedule you have to
 * remember to press "save" on is a schedule that never sticks.
 */
export function ScheduleSection({ t, schedule, onSave }) {
  const [v, setV] = useState(() => ({ ...(schedule || {}) }))
  useEffect(() => { setV({ ...(schedule || {}) }) }, [schedule])

  const patch = (next) => {
    setV((prev) => ({ ...prev, ...next }))
    onSave({ ...v, ...next })
  }

  const timeRow = (key) => (
    <label className="row small" style={{ gap: 8, justifyContent: 'space-between' }}>
      <span className="muted">{t(key === 'morning' ? 'sched_morning'
        : key === 'evening' ? 'sched_evening' : 'sched_digest')}</span>
      <input className="inp" type="time" value={v[key] || ''}
             style={{ width: 110 }}
             onChange={(e) => patch({ [key]: e.target.value })} />
    </label>
  )

  return (
    <div className="col">
      <label className="small muted">{t('checkin_times')}</label>
      {timeRow('morning')}
      {timeRow('evening')}
      {timeRow('digest')}
      <label className="row small muted" style={{ gap: 8 }}>
        <input type="checkbox" checked={v.enabled !== false}
               onChange={(e) => patch({ enabled: e.target.checked })} />
        {t('sched_enabled')}
      </label>
    </div>
  )
}

/**
 * Password — New + Confirm only, as the design specifies. It needs a live
 * session, so it is not a way into someone else's account.
 */
export function PasswordSection({ t, user }) {
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')

  useEffect(() => { setErr(''); setOk('') }, [user])

  if (!user) {
    return (
      <div className="col">
        <label className="small muted">{t('password_section')}</label>
        <div className="small muted">{t('auth_not_signed_in')}</div>
      </div>
    )
  }

  async function submit(e) {
    e.preventDefault()
    setErr(''); setOk('')
    setBusy(true)
    try {
      await api.changePassword(pw, pw2)
      setOk(t('password_changed'))
      setPw(''); setPw2('')
    } catch (ex) {
      setErr(authMessage(t, ex.message))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="col">
      <label className="small muted">{t('password_section')}</label>
      <form onSubmit={submit} className="col">
        <input className="inp" type="password" value={pw}
               onChange={(e) => setPw(e.target.value)}
               placeholder={t('new_password')} autoComplete="new-password" required />
        <input className="inp" type="password" value={pw2}
               onChange={(e) => setPw2(e.target.value)}
               placeholder={t('auth_confirm')} autoComplete="new-password" required />
        {err ? <div className="small" style={{ color: 'var(--danger)' }}>{err}</div> : null}
        {ok ? <div className="small" style={{ color: 'var(--ok)' }}>{ok}</div> : null}
        <button className="btn" type="submit" disabled={busy}>
          {t('save')}
        </button>
      </form>
    </div>
  )
}

export function SettingsPanel({ t, lang, setLang, theme, setTheme, voiceOut,
  setVoiceOut, onClose, user, onAuthed, onSignOut,
  schedule, onSaveSchedule }) {
  return (
    <Panel title={t('settings')} onClose={onClose}>
      <div className="col">
        <label className="small muted">{t('language')}</label>
        <select className="sel" value={lang} onChange={(e) => setLang(e.target.value)}>
          {LANGS.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
        </select>

        <label className="small muted">{t('theme')}</label>
        <div className="row">
          <button className={'btn ' + (theme === 'dark' ? '' : 'ghost')}
                  onClick={() => setTheme('dark')}>{t('dark_mode')}</button>
          <button className={'btn ' + (theme === 'light' ? '' : 'ghost')}
                  onClick={() => setTheme('light')}>{t('light_mode')}</button>
        </div>

        <label className="small muted">{t('voice_out')}</label>
        <div className="row">
          <button className={'btn ' + (voiceOut ? '' : 'ghost')}
                  onClick={() => setVoiceOut(true)}>{t('on_lbl')}</button>
          <button className={'btn ' + (voiceOut ? 'ghost' : '')}
                  onClick={() => setVoiceOut(false)}>{t('off_lbl')}</button>
        </div>

        <div className="hr" />

        <ScheduleSection t={t} schedule={schedule} onSave={onSaveSchedule} />

        <div className="hr" />

        <PasswordSection t={t} user={user} />

        <div className="hr" />

        <AccountSection t={t} user={user} onAuthed={onAuthed}
                        onSignOut={onSignOut} />
      </div>
    </Panel>
  )
}
