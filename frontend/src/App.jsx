import { useCallback, useEffect, useRef, useState } from 'react'
import * as nav from './lib/nav'
import { api, getToken, setToken, setApiLang } from './lib/api'
import { tr } from './lib/i18n'
import { browserAsr, startRecording } from './lib/wavRecorder'
import { syntheticThudWav, watchForThud } from './lib/thud'
import HomeView from './components/HomeView'
import ChatView from './components/ChatView'
import HealthView from './components/HealthView'
import MedicinesView from './components/MedicinesView'
import AlertOverlay from './components/AlertOverlay'
import EmergencyView from './components/EmergencyView'
import MonitorView from './components/MonitorView'
import CheckInOverlay from './components/CheckInOverlay'
import { ActivityPanel, NotifyPanel, SettingsPanel } from './components/Panels'

// \uFE0F (variation selector) is a combining character, so it has to sit
// outside the class — inside one it silently fails to match.
const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{2190}-\u{21FF}]|\u{FE0F}/gu
// Markdown punctuation must never be spoken aloud ("underscore", "star").
const MD = /[*_~`#|>[\]()]/g

const SPEAK_LANG = { hi: 'hi-IN', en: 'en-US', bn: 'bn-IN', ta: 'ta-IN', te: 'te-IN',
  mr: 'mr-IN', gu: 'gu-IN', es: 'es-ES', fr: 'fr-FR' }

function speak(text, lang) {
  if (!('speechSynthesis' in window) || !text) return
  const clean = String(text)
    .replace(EMOJI, ' ')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s*/gm, '')
    .replace(/^\s{0,3}[-*+]\s+/gm, '')
    .replace(MD, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!clean) return
  try {
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(clean)
    u.lang = SPEAK_LANG[lang] || 'en-US'
    u.rate = 0.95
    window.speechSynthesis.speak(u)
  } catch (e) { /* TTS optional */ }
}

const EMPTY_STATE = { profile: {}, meds: [], activity: [], notifications: [] }

export default function App() {
  const [lang, setLang] = useState(() => localStorage.getItem('saavren.lang.v2') || 'en')
  const [theme, setTheme] = useState(() => localStorage.getItem('saavren.theme') || 'dark')
  // D5 — who is looking at the screen: the elder, or the family on the monitor
  const [role, setRole] = useState(() => localStorage.getItem('saavren.role') || 'elder')
  const [voiceOut, setVoiceOut] = useState(() => localStorage.getItem('saavren.voice') !== '0')
  const [listenFall, setListenFall] = useState(
    () => localStorage.getItem('saavren.fallwatch') === '1')

  const [state, setState] = useState(EMPTY_STATE)
  const [health, setHealth] = useState(null)
  const [convs, setConvs] = useState([])
  const [activeId, setActiveId] = useState(null)

  const [view, setView] = useState('home')
  const [panel, setPanel] = useState(null)
  const [sideOpen, setSideOpen] = useState(true)
  const [msgs, setMsgs] = useState([])
  const [draft, setDraft] = useState('')
  const [typing, setTyping] = useState(false)
  const [busy, setBusy] = useState(false)
  const [recording, setRecording] = useState(false)
  const [recMs, setRecMs] = useState(0)
  const [level, setLevel] = useState(0)
  const [toast, setToast] = useState('')

  // Accounts are optional: no token just means nobody is signed in.
  const [user, setUser] = useState(null)
  const [routine, setRoutine] = useState(null)
  const [board, setBoard] = useState(null)
  const [asrBroken, setAsrBroken] = useState(false)

  // D3 + D4
  const [alarm, setAlarm] = useState(null)
  const [remaining, setRemaining] = useState(0)
  const [emergency, setEmergency] = useState(null)

  // D5 — the monitor's own live payload
  const [mon, setMon] = useState(null)
  // D7 — Sehat Board payload
  const [sehat, setSehat] = useState(null)
  // D6 — the daily companion's proactive check-in
  const [checkin, setCheckin] = useState(null)   // {kind, questions} | null
  // "not now" must mean "not today" — an in-memory flag would just pop the
  // check-in back up on every reload, which is how you lose an elder's trust.
  const [ckDismissed, setCkDismissed] = useState(
    () => localStorage.getItem('saavren.ck.dismissed') || '')

  const recRef = useRef(null)
  const timerRef = useRef(null)
  const autoRef = useRef(null)
  const watchRef = useRef(null)

  const t = useCallback((k, v) => tr(lang, k, v), [lang])

  // server ASR = anything except 'browser' (mms | groq)
  const serverAsr = (health?.asr_mode || 'browser') !== 'browser'

  useEffect(() => { document.documentElement.dataset.theme = theme }, [theme])
  // A token in storage is not proof it still works — it may have expired or
  // the database may have been replaced. Ask the server who it belongs to.
  useEffect(() => {
    if (!getToken()) return
    let alive = true
    api.me()
      .then((r) => { if (alive && r?.user) setUser(r.user) })
      .catch(() => { if (alive) setToken(null) })
    return () => { alive = false }
  }, [])

  useEffect(() => {
    let alive = true
    api.routine().then((r) => { if (alive) setRoutine(r) }).catch(() => {})
    api.board().then((b) => { if (alive) setBoard(b) }).catch(() => {})
    return () => { alive = false }
  }, [state])

  const toggleAlarm = async (key, alarm) => {
    try {
      setRoutine(await api.setRoutineAlarm(key, alarm))
    } catch (e) {
      setToast('\u26a0 ' + (e.message || 'alarm nahi badla'))
    }
  }

  const saveSchedule = async (patch) => {
    try {
      const d = await api.setCheckinSchedule(patch)
      setState((st) => ({ ...st, checkin_schedule: d.schedule }))
    } catch (e) {
      setToast('\u26a0 ' + (e.message || 'schedule save nahi hua'))
    }
  }

  const onAuthed = async (u, token) => {
    setToken(token)
    setUser(u)
    // an account knows which seat it sits in
    if (u?.role === 'family' || u?.role === 'elder') setRole(u.role)
    setPanel(null)
    // the seeded profile belongs to the demo elder; once a real person signs
    // in as the elder, the profile is theirs
    if (u?.role === 'elder' && u?.name) {
      try {
        const d = await api.saveProfile({ name: u.name })
        setState(d.state); afterEdit()
      } catch (e) { /* the profile is cosmetic — never block a sign-in on it */ }
    }
  }

  const onSignOut = () => {
    api.logout().catch(() => {})
    setToken(null)
    setUser(null)
  }

  useEffect(() => { localStorage.setItem('saavren.theme', theme) }, [theme])
  useEffect(() => { localStorage.setItem('saavren.role', role) }, [role])
  useEffect(() => {
    localStorage.setItem('saavren.lang.v2', lang)
    setApiLang(lang)   // so every later request answers in this language too
  }, [lang])
  useEffect(() => { localStorage.setItem('saavren.voice', voiceOut ? '1' : '0') }, [voiceOut])
  useEffect(() => { localStorage.setItem('saavren.fallwatch', listenFall ? '1' : '0') },
    [listenFall])

  const refresh = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([api.state(), api.conversations()])
      setState(s)
      setConvs(c.conversations || [])
    } catch (e) { /* offline */ }
  }, [lang])

  const refreshSehat = useCallback(async () => {
    try { setSehat(await api.sehat()) } catch (e) { /* offline */ }
  }, [])

  const refreshMon = useCallback(async () => {
    try { setMon(await api.monitor()) } catch (e) { /* offline */ }
  }, [])

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
    refresh()
    refreshSehat()
  }, [refresh, refreshSehat])

  // D6 — the companion asks first. Polled once a minute on the elder's seat
  // only, and never while an alarm or an emergency is on screen.
  //
  // It must NOT ask the instant the app opens: the check-in is a full-screen
  // overlay, so firing it at t=0 means the first thing anyone sees is a dark
  // scrim where the app should be. Let the home screen be seen first.
  const CHECKIN_GRACE_MS = 45000
  const bootedAt = useRef(Date.now())
  const todayKey = () => new Date().toISOString().slice(0, 10)
  useEffect(() => {
    if (role !== 'elder') { setCheckin(null); return }
    let cancelled = false
    const look = async () => {
      try {
        const d = await api.checkinDue(lang)
        if (cancelled) return
        // the home card still shows that a check-in is waiting, so the elder
        // can start it by hand during the grace period
        setCkDue(d.due || null)
        if (!d.due) return
        if (ckDismissed === `${d.due.kind}:${todayKey()}`) return
        // never interrupt an emergency
        if (alarm?.status === 'ringing' || alarm?.status === 'escalated') return
        if (view === 'emergency') return
        // and never talk over a conversation
        if (view === 'chat') return
        if (Date.now() - bootedAt.current < CHECKIN_GRACE_MS) return
        setCheckin({ kind: d.due.kind, questions: d.questions })
      } catch (e) { /* offline */ }
    }
    look()
    const id = setInterval(look, 60000)
    return () => { cancelled = true; clearInterval(id) }
  }, [role, lang, ckDismissed, alarm?.status, view])

  // the home card needs to know a check-in is waiting even before the
  // once-a-minute poll fires, so a tap always opens it
  const [ckDue, setCkDue] = useState(null)

  const startCheckinNow = async () => {
    try {
      const d = await api.checkinDue(lang, true)   // by hand, any hour
      if (d.due) setCheckin({ kind: d.due.kind, questions: d.questions })
      else setToast('⚠ ' + t('checkin_none'))
    } catch (e) {
      setToast('⚠ ' + (e.message || 'check-in unavailable'))
    }
  }

  const dismissCheckin = (key) => {
    localStorage.setItem('saavren.ck.dismissed', key)
    setCkDismissed(key)
  }

  const finishCheckin = (rec) => {
    setCkDismissed(`${checkin?.kind}:${todayKey()}`)
    setCheckin(null); setCkDue(null)
    if (rec?.mood === 'bad') setToast('🩺 ' + t('checkin_sent'))
    afterEdit()
  }
  const skipCheckin = async (kind) => {
    try { await api.checkinSkip(kind, lang) } catch (e) { /* offline */ }
    dismissCheckin(`${kind}:${todayKey()}`)
    setCheckin(null)
  }

  // The monitor is a live screen: poll while you are on it, stop when you are
  // not, so an idle tab is not hammering the server every 5 seconds.
  useEffect(() => {
    if (role !== 'family') return
    refreshMon()
    const id = setInterval(refreshMon, 5000)
    return () => clearInterval(id)
  }, [role, refreshMon])

  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToast(''), 4200)
    return () => clearTimeout(id)
  }, [toast])

  const push = useCallback((m) => setMsgs((x) => [...x, m]), [])

  /* ------------------------------------------------------------ chat ---- */
  // `as` is who is asking: the elder, or a family member on the monitor. The
  // same brain answers both — it just sits in a different chair.
  async function send(text, as = role) {
    const msg = (text ?? draft).trim()
    if (!msg || busy) return
    setDraft('')
    setView('chat')
    push({ role: 'user', text: msg })
    setBusy(true); setTyping(true)
    try {
      const d = await api.chat(msg, lang, activeId, false, as)
      if (d.kind === 'triage') {
        push({ role: 'assistant', kind: 'triage', triage: d.triage })
        if (voiceOut) speak(d.triage.calm_reply, lang)
      } else {
        push({
          role: 'assistant', text: d.reply, actions: d.applied, stream: true,
          note: d.source === 'offline-fallback'
            ? t('offline_note') + (d.offline_reason ? ' — ' + d.offline_reason : '')
            : '',
        })
        if (voiceOut) speak(d.reply, lang)
      }
      setActiveId(d.conversation_id)
      if (d.state) setState(d.state)
    } catch (e) {
      push({ role: 'assistant', text: '⚠ ' + (e.message || 'network error') })
    }
    setTyping(false); setBusy(false)
    refresh()
  }

  /* ------------------------------------------------------------- mic ---- */
  async function startMic() {
    if (recording) { stopMic(); return }
    // server ASR = anything except 'browser' (mms | groq)
    if ((health?.asr_mode || 'browser') === 'browser' || asrBroken) {
      return browserListen()
    }
    try {
      const r = await startRecording(setLevel)
      recRef.current = r
      setRecording(true); setRecMs(0)
      timerRef.current = setInterval(() => setRecMs((m) => m + 100), 100)
      autoRef.current = setTimeout(() => stopMic(), 12000)
    } catch (e) {
      setToast('🎙️ mic permission / device error: ' + (e.message || ''))
    }
  }

  async function browserListen() {
    setView('chat')
    setRecording(true)
    push({ role: 'user', text: '🎙️ …' })
    try {
      const text = await browserAsr(lang)
      setRecording(false)
      setMsgs((x) => x.slice(0, -1).concat([{ role: 'user', text: '🎙️ ' + text }]))
      if (role === 'family') { await send(text, 'family'); setBusy(false); return }
      setTyping(true)
      const d = await api.chat(text, lang, activeId, true)
      setActiveId(d.conversation_id)
      push({ role: 'assistant', kind: 'triage', triage: d.triage, note: t('asr_browser') })
      if (voiceOut) speak(d.triage.calm_reply, lang)
      if (d.state) setState(d.state)
      setTyping(false)
      refresh()
    } catch (e) {
      setRecording(false)
      setMsgs((x) => x.slice(0, -1))
      setToast('🎙️ ' + (e.message || 'awaz samajh nahi aayi'))
      setTyping(false)
    }
  }

  async function stopMic() {
    clearInterval(timerRef.current); clearTimeout(autoRef.current)
    setRecording(false)
    let out
    try { out = recRef.current?.stop() } catch (e) { return }
    if (!out || !out.blob || out.blob.size < 2000) {
      setToast('🎙️ kuch suna nahi gaya — mic check karke phir boliye')
      return
    }
    setBusy(true); setTyping(true)
    push({ role: 'user', text: '🎙️ …' })
    // D5 — a family member's voice is a question about the elder, not an
    // emergency. Transcribe it, then ask the monitor brain. No alarm, ever.
    if (role === 'family') {
      try {
        const d = await api.transcribe(out.blob)
        setMsgs((x) => x.slice(0, -1))
        setTyping(false); setBusy(false)
        if (d.text) await send(d.text, 'family')
        return
      } catch (e) {
        setMsgs((x) => x.slice(0, -1))
        setTyping(false); setBusy(false)
        try {
          const text = await browserAsr(lang)
          await send(text, 'family')
        } catch (e2) {
          setToast('🎙️ ' + (e2.message || 'awaz samajh nahi aayi'))
        }
        return
      }
    }
    try {
      const d = await api.voiceSos(out.blob)
      setMsgs((x) => x.slice(0, -1).concat([{ role: 'user', text: '🎙️ ' + d.transcript }]))
      push({ role: 'assistant', kind: 'triage', triage: d.triage })
      if (voiceOut) speak(d.triage.calm_reply, lang)
      if (d.state) setState(d.state)
      setTyping(false); refresh()
      return
    } catch (e) {
      setAsrBroken(true)
      try {
        setMsgs((x) => x.slice(0, -1))
        const text = await browserAsr(lang)
        push({ role: 'user', text: '🎙️ ' + text })
        const d = await api.chat(text, lang, activeId, true)
        setActiveId(d.conversation_id)
        push({ role: 'assistant', kind: 'triage', triage: d.triage,
               note: t('asr_browser') })
        if (voiceOut) speak(d.triage.calm_reply, lang)
        if (d.state) setState(d.state)
      } catch (e2) {
        setMsgs((x) => x.slice(0, -1))
        setToast('🎙️ ' + (e2.message || 'awaz samajh nahi aayi'))
      }
    }
    setTyping(false); setBusy(false)
  }

  async function attach(file) {
    setView('chat')
    push({ role: 'user', text: '📎 ' + file.name })
    setBusy(true); setTyping(true)
    try {
      const d = await api.scan(file, lang)
      push({ role: 'assistant', text: d.summary || t('empty'),
             note: d.source === 'offline-fallback' ? t('offline_note') : '' })
      if (d.state) setState(d.state)
      if (voiceOut) speak(d.summary, lang)
    } catch (e) {
      push({ role: 'assistant', text: '⚠ ' + (e.message || 'scan failed') })
    }
    setTyping(false); setBusy(false); refresh()
  }

  const openConversation = async (id) => {
    setActiveId(id)
    try {
      const c = await api.conversation(id)
      setMsgs((c.messages || []).map((m) => (
        m.role === 'user' ? { role: 'user', text: m.content }
          : m.kind === 'triage' ? { role: 'assistant', kind: 'triage', triage: m.content }
            : { role: 'assistant', text: m.content, actions: m.actions })))
      setView('chat')
    } catch (e) { /* ignore */ }
  }

  const newChat = () => { setActiveId(null); setMsgs([]); setView('chat') }

  /* ------------------------------------------------------ D3: alarm ----- */
  const raiseFall = useCallback(async (confidence, source, features) => {
    try {
      const d = await api.fall(confidence, source, features, lang)
      setAlarm(d.alarm)
      setRemaining(d.alarm?.grace || 20)
      if (d.state) setState(d.state)
    } catch (e) {
      setToast('⚠ ' + (e.message || 'alarm start nahi hua'))
    }
  }, [lang])

  const pollAlarm = useCallback(async () => {
    try {
      const d = await api.alarm()
      if (!d.alarm) { setAlarm(null); return }
      setAlarm(d.alarm)
      setRemaining(d.remaining)
      if (d.state) setState(d.state)
    } catch (e) { /* offline */ }
  }, [])

  // keep the overlay truthful while it counts down
  useEffect(() => {
    if (!alarm || alarm.status !== 'ringing') return
    const id = setInterval(pollAlarm, 1000)
    return () => clearInterval(id)
  }, [alarm?.id, alarm?.status, pollAlarm])

  // background thud watch (opt-in from the sidebar)
  useEffect(() => {
    if (!listenFall) { watchRef.current?.stop(); watchRef.current = null; return }
    let cancelled = false
    watchForThud({
      onThud: (f) => {
        if (cancelled) return
        // Only a confident 'thud' rings the alarm. A 'possible' (loud laugh,
        // dropped plate) is logged, never escalated — a false alarm at 3 a.m.
        // costs more trust than a missed one.
        if (f.verdict === 'thud') {
          raiseFall(f.score, 'browser', f)
        } else {
          setToast(`🧪 possible thud — score ${f.score}`)
        }
      },
    }).then((w) => {
      if (cancelled) { w.stop(); return }
      watchRef.current = w
    }).catch((e) => {
      setToast('🎧 fall-watch start nahi hua: ' + (e.message || ''))
      setListenFall(false)
    })
    return () => { cancelled = true; watchRef.current?.stop(); watchRef.current = null }
  }, [listenFall, raiseFall])

  // escalated -> open the D4 emergency screen automatically
  useEffect(() => {
    if (!alarm || alarm.status !== 'escalated') return
    const eid = alarm.emergency_id
    if (!eid) return
    api.emergency(eid).then((r) => setEmergency(r)).catch(() => {})
  }, [alarm?.id, alarm?.status, alarm?.emergency_id])

  const logCall = async (who) => {
    if (!emergency) return
    const d = await api.logCall(emergency.id, who)
    setEmergency(d.record)
    setToast(`📞 call logged — ${who}`)
  }
  const closeEmergency = async () => {
    if (!emergency) return
    await api.closeEmergency(emergency.id)
    setEmergency(null)
    refresh()
  }
  const printCard = () => {
    const el = document.getElementById('ecard')
    if (!el) return
    const w = window.open('', '_blank', 'width=760,height=900')
    if (!w) { setToast('popup blocked — allow popups to print'); return }
    w.document.write(
      `<html><head><title>${t('print_title')}</title><style>` +
      'body{font-family:system-ui,sans-serif;padding:28px;color:#000}' +
      'h1{font-size:20px}table{border-collapse:collapse;width:100%}' +
      'td{padding:6px 8px;border-bottom:1px solid #ddd;font-size:14px}' +
      'td:first-child{color:#555;width:150px}' +
      '</style></head><body>' + el.innerHTML + '</body></html>')
    w.document.close()
    w.focus()
    setTimeout(() => w.print(), 300)
  }

  /* ------------------------------------------------------ D5: monitor ---- */
  const askAboutElder = (q) => {
    const name = (state?.profile?.name || '').split(' ')[0] || 'them'
    setActiveId(null)
    setMsgs([{ role: 'assistant', text:
      `${t('monitor_greet', { name })} ${t('monitor_hint', { name })}` }])
    setView('chat')
    if (q) setDraft(q)
  }

  const ackMonitor = async () => {
    // whoever is signed in owns the acknowledgement; otherwise fall back to
    // the name on file, and finally to the generic "family"
    const who = user?.name
      || (mon?.profile?.emergency_contact || 'family').split(/[ (+]/)[0]
    try {
      const d = await api.ackMonitor(who || 'family')
      setMon(d)
      setState((st) => ({ ...st, monitor: d.monitor }))
      setToast(`✓ ${t('acked_by', { who: d.monitor?.acked_by || 'family' })}`)
    } catch (e) {
      setToast('⚠ ' + (e.message || 'ack failed'))
    }
  }

  const openIncident = (rec) => { setEmergency(rec); setView('emergency') }

  const openEcard = async () => {
    // The Emergency Card is what a paramedic reads, and it is built from the
    // profile and medicines — so it has to be reachable BEFORE anything has
    // gone wrong. Opening only the last incident made this button a dead end
    // (a "Nothing here yet" toast) on every fresh install, which is the worst
    // possible behaviour for the one screen that matters most.
    try {
      const d = await api.emergencies()
      if (d.emergencies?.length) {
        setEmergency(d.emergencies[0]); setView('emergency'); return
      }
    } catch (e) { /* fall through to the standalone card */ }
    try {
      const c = await api.ecard()
      const h = await api.hospitals().catch(() => ({ hospitals: [] }))
      setEmergency({
        kind: 'card', ts: Math.floor(Date.now() / 1000),
        card: c.card || {}, hospitals: h.hospitals || [], text: c.text || '',
      })
      setView('emergency')
    } catch (e) {
      setToast('\u26a0 ' + (e.message || 'could not open the emergency card'))
    }
  }

  const cancelAlarm = async () => {
    const d = await api.cancelAlarm()
    setAlarm(d.alarm); if (d.state) setState(d.state)
  }
  const helpAlarm = async () => {
    const d = await api.helpAlarm()
    setAlarm(d.alarm); if (d.state) setState(d.state)
    if (voiceOut) speak(t('fall_escalated'), lang)
    refresh()
  }
  const sos = async () => {
    const d = await api.sos()
    setAlarm(d.alarm); if (d.state) setState(d.state)
    if (d.alarm?.emergency_id) {
      try { setEmergency(await api.emergency(d.alarm.emergency_id)) } catch (e) { /* ignore */ }
      setView('emergency')
    }
  }
  const testThud = async () => {
    setToast('🧪 ' + t('test_thud'))
    try {
      const d = await api.analyzeThud(syntheticThudWav(3), lang, true)
      setToast(`🧪 score ${d.analysis.score} · ${d.analysis.verdict}`
        + ` · peak ${d.analysis.peak} · low ${d.analysis.low_ratio}`)
      if (d.alarm) { setAlarm(d.alarm); setRemaining(d.alarm.grace) }
      if (d.state) setState(d.state)
    } catch (e) { setToast('⚠ ' + (e.message || 'test failed')) }
  }

  /* --------------------------------------------------------- actions ---- */
  const addMed = async (name, time, note) => {
    try {
      const d = await api.addMed(name, time, note)
      setState(d.state); afterEdit(); return true
    } catch (e) {
      setToast('\u26a0 ' + (e.message || 'medicine add nahi hui')); return false
    }
  }
  const toggleMed = async (name) => {
    try {
      const d = await api.toggleMed(name)
      setState(d.state); afterEdit()
    } catch (e) {
      setToast('\u26a0 ' + (e.message || 'update nahi hua'))
    }
  }
  const deleteMed = async (id) => {
    try {
      const d = await api.deleteMed(id)
      setState(d.state); afterEdit()
    } catch (e) {
      setToast('\u26a0 ' + (e.message || 'delete nahi hua'))
    }
  }
  const readAll = async () => { await api.readNotifications(); refresh() }
  const afterEdit = async () => { refresh(); refreshSehat() }

  const unread = (state?.notifications || []).filter((n) => !n.read).length
  const family = role === 'family'
  const monUnread = mon?.unread ?? unread

  // switching seats always lands on that seat's home screen
  useEffect(() => { setView('home'); setPanel(null) }, [role])

  const switchRole = (next) => { setRole(next); setMsgs([]); setActiveId(null) }

  /* ---- back -------------------------------------------------------------
     One page, no router: without this the phone's back gesture closed the
     whole app. Every open layer gets a history entry, so back closes the top
     one — a panel first, then the screen under it. */
  const onScreen = useRef({ view, panel })
  onScreen.current = { view, panel }

  const canGoBack = !!panel || view !== 'home'

  // A ringing alarm or a running check-in must survive a stray back press.
  const blocking = !!(alarm || checkin)
  useEffect(() => { nav.setBlocked(blocking) }, [blocking])

  // Keeps browser history in step with whatever is open, however it opened.
  useEffect(() => {
    nav.sync(canGoBack ? (panel ? 2 : 1) : 0, () => {
      const s = onScreen.current
      if (s.panel) setPanel(null)
      else if (s.view !== 'home') setView('home')
    })
  }, [view, panel])

  useEffect(() => {
    nav.arm()
    const onPop = () => nav.handlePopState()
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  return (
    <div className="app">
      {!family && (
      <aside className={'side' + (sideOpen ? '' : ' collapsed')}>
        <div className="brand">
          <div className="logo">S</div>
          <div><b>Saavren</b><span>{t('tagline')}</span></div>
        </div>
        <button className="btn wide" onClick={newChat}>+ {t('new_chat')}</button>
        <div style={{ flex: 1, overflow: 'auto', marginTop: 6 }}>
          {convs.map((c) => (
            <button key={c.id} className="btn ghost wide small"
                    style={{ justifyContent: 'flex-start', marginBottom: 6,
                      textAlign: 'left' }}
                    onClick={() => openConversation(c.id)}>
              {(c.title || t('new_chat')).slice(0, 30)}
            </button>
          ))}
        </div>
        <button className="btn ghost wide small" onClick={() => setPanel('settings')}>
          ⚙ {t('settings')}
        </button>
        <label className="row small muted" style={{ gap: 8 }}>
          <input type="checkbox" checked={listenFall}
                 onChange={(e) => setListenFall(e.target.checked)} />
          {t('mic_watch')}
        </label>
      </aside>
      )}

      <main className="main">
        <div className="topbar">
          {canGoBack && (
            <button className="iconbtn backbtn" onClick={() => nav.goBack()}
                    title={t('back')} aria-label={t('back')}>←</button>
          )}
          {!family && (
            <button className="iconbtn" onClick={() => setSideOpen((s) => !s)}>☰</button>
          )}
          <b>Saavren</b>
          {family && <span className="chip">👨‍👩‍👧 {t('monitor')}</span>}
          <span className="spacer" />
          <button className="iconbtn" onClick={() => setPanel('activity')}>🕘</button>
          <button className="iconbtn" onClick={() => setPanel('notify')}>
            🔔{monUnread ? <span className="badge">{monUnread}</span> : ''}
          </button>
          {/* the monitor has no sidebar, so its Settings — and therefore
              signing out — has to live here instead */}
          {family && (
            <button className="iconbtn" title={t('settings')}
                    onClick={() => setPanel('settings')}>⚙</button>
          )}
          {family ? (
            <button className="btn ghost small" onClick={() => switchRole('elder')}>
              🧓 {t('elder_view')}
            </button>
          ) : (
            <button className="btn ghost small" onClick={() => switchRole('family')}>
              👨‍👩‍👧 {t('family_view')}
            </button>
          )}
          {/* the SOS button belongs to the elder's screen only — on the
              monitor it is the Alerts bell, per the design */}
          {!family && (
            <button className="btn danger small" onClick={sos}>{t('sos')}</button>
          )}
          <select className="langsel" value={lang}
                  onChange={(e) => setLang(e.target.value)}>
            {[['hi','हिन्दी'],['en','English'],['bn','বাংলা'],['ta','தமிழ்'],
              ['te','తెలుగు'],['mr','मराठी'],['gu','ગુજરાતી'],['es','Español'],
              ['fr','Français']].map(([c, n]) => <option key={c} value={c}>{n}</option>)}
          </select>
        </div>

        {view === 'home' && family && (
          <div className="view">
            <MonitorView t={t} lang={lang} data={mon} live
                         onAsk={(q) => askAboutElder(q)}
                         onOpenIncident={openIncident}
                         onAck={ackMonitor} onCall={logCall} />
          </div>
        )}
        {/* Shanti Devi is seeded demo data, not whoever is using the app.
            Say so until a real account takes over the profile. */}
        {!family && state?.demo && !user && (
          <div className="demobar">
            <span>ℹ️</span>
            <span className="small">
              {t('demo_banner', { n: (state?.profile?.name || '').split(' ')[0] })}
            </span>
          </div>
        )}

        {view === 'meds' && !family && (
          <MedicinesView t={t} state={state} busy={busy}
                         onAdd={addMed} onToggle={toggleMed}
                         onDelete={deleteMed} />
        )}
        {view === 'home' && !family && (
          <div className="view">
            <HomeView t={t} state={state} onAsk={() => setView('chat')}
                      onGo={(v) => {
                        if (v === 'meds' || v === 'health') return setView(v)
                        // 'chat' is a screen, not a panel — routing it to
                        // setPanel('chat') matched nothing and the tile simply
                        // did nothing when tapped.
                        if (v === 'chat') return newChat()
                        return setPanel(v)
                      }}
                      onTestThud={testThud}
                      checkinDue={ckDue}
                      onStartCheckin={startCheckinNow} />
          </div>
        )}
        {view === 'emergency' && (
          <div className="view">
            <EmergencyView rec={emergency} t={t} lang={lang} onCall={logCall}
                           onClose={() => setView('home')}
                           onPrint={printCard} />
          </div>
        )}
        {view === 'health' && (
          <div className="view">
            <HealthView t={t} state={state} onToggleMed={toggleMed}
                        onDeleteMed={deleteMed} onAddMed={addMed}
                        board={sehat} setBoard={setSehat} />
          </div>
        )}
        {view === 'chat' && (
          <div className="chatwrap">
            <ChatView msgs={msgs} typing={typing} t={t} draft={draft}
                      setDraft={setDraft} onSend={() => send()}
                      onMic={startMic} recording={recording} recMs={recMs}
                      onAttach={attach} busy={busy} />
          </div>
        )}

        <div className="dock">
          <button className="iconbtn" onClick={() => setView('home')}>🏠</button>
          <button className="iconbtn" onClick={() => {
            if (family && !msgs.length) askAboutElder('')
            setView('chat')
          }}>💬</button>
          {!family && (
            <button className="iconbtn" onClick={() => setView('health')}>❤️</button>
          )}
          <button className="iconbtn" onClick={openEcard}
                  title={t('ecard')}>🚨</button>
          <button className="iconbtn" onClick={startMic}>🎙️</button>
        </div>
      </main>

      {panel === 'settings' && (
        <SettingsPanel t={t} lang={lang} setLang={setLang} theme={theme}
                       setTheme={setTheme} voiceOut={voiceOut} setVoiceOut={setVoiceOut}
                       onClose={() => setPanel(null)} user={user}
                       onAuthed={onAuthed} onSignOut={onSignOut}
                       schedule={state?.checkin_schedule}
                       onSaveSchedule={saveSchedule} />
      )}
      {panel === 'activity' && (
        <ActivityPanel t={t} lang={lang} state={state} onRead={readAll}
                       onClose={() => setPanel(null)} routine={routine}
                       onToggleAlarm={toggleAlarm} board={board} />
      )}
      {panel === 'notify' && (
        <NotifyPanel t={t} lang={lang} state={state} onRead={readAll}
                     onClose={() => setPanel(null)} />
      )}

      {checkin && !alarm ? (
        <CheckInOverlay kind={checkin.kind} questions={checkin.questions}
                        t={t} lang={lang} serverAsr={serverAsr}
                        voiceOut={voiceOut} speak={speak}
                        onDone={finishCheckin} onSkip={skipCheckin} />
      ) : null}

      <AlertOverlay alarm={alarm} remaining={remaining} t={t}
                    onCancel={cancelAlarm} onHelp={helpAlarm}
                    onDone={() => { setAlarm(null); refresh() }} />

      {toast && <div className="toast">{toast}</div>}
      {level > 0.02 && (
        <div style={{ position: 'fixed', bottom: 74, left: '50%',
          transform: 'translateX(-50%)', width: 160, height: 4,
          background: 'var(--line)', borderRadius: 4, overflow: 'hidden' }}>
          <div style={{ width: `${level * 100}%`, height: '100%',
            background: 'var(--ok)' }} />
        </div>
      )}
    </div>
  )
}
