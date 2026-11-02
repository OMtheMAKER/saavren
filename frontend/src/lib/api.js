const J = (r) => {
  if (!r.ok) {
    return r.json().catch(() => ({})).then((d) => {
      const e = new Error(d.detail || d.error || r.statusText || `HTTP ${r.status}`)
      e.status = r.status
      throw e
    })
  }
  return r.json()
}

/* ---- session token ----------------------------------------------------
   Login is optional, so every call works without one. When a token is
   present it rides along so the server knows who is asking. */
let TOKEN = null
try { TOKEN = localStorage.getItem('saavren.token') || null } catch (e) { /* private mode */ }

export const getToken = () => TOKEN
export const setToken = (t) => {
  TOKEN = t || null
  try {
    if (TOKEN) localStorage.setItem('saavren.token', TOKEN)
    else localStorage.removeItem('saavren.token')
  } catch (e) { /* private mode */ }
}

/* ---- language ---------------------------------------------------------
   Sent on every request so the server can render seeded demo text in the
   language on screen. Without it, any reply carrying `state` would hand back
   English and quietly undo the language switch. */
let LANG = 'en'
try { LANG = localStorage.getItem('saavren.lang.v2') || 'en' } catch (e) { /* private mode */ }

export const setApiLang = (l) => {
  LANG = l || 'en'
  try { localStorage.setItem('saavren.lang.v2', LANG) } catch (e) { /* private mode */ }
}

const H = () => ({
  ...(TOKEN ? { Authorization: 'Bearer ' + TOKEN } : {}),
  'X-Saavren-Lang': LANG,
})
const JH = () => ({ 'Content-Type': 'application/json', ...H() })

export const api = {
  // ---- accounts (optional) ---------------------------------------------
  me: () => fetch('/api/auth/me', { headers: H() }).then(J),
  accountCount: () => fetch('/api/auth/accounts').then(J),
  signup: (name, username, password, role) =>
    fetch('/api/auth/signup', {
      method: 'POST', headers: JH(),
      body: JSON.stringify({ name, username, password, role }),
    }).then(J),
  login: (username, password) =>
    fetch('/api/auth/login', {
      method: 'POST', headers: JH(),
      body: JSON.stringify({ username, password }),
    }).then(J),
  logout: () => fetch('/api/auth/logout', { method: 'POST', headers: H() }).then(J),
  changePassword: (password, confirm) =>
    fetch('/api/auth/password', {
      method: 'POST', headers: JH(),
      body: JSON.stringify({ password, confirm }),
    }).then(J),

  // ---- routine planner + weekly board ----------------------------------
  routine: () => fetch('/api/routine', { headers: H() }).then(J),
  setRoutineAlarm: (key, alarm) =>
    fetch('/api/routine/alarm', {
      method: 'POST', headers: JH(),
      body: JSON.stringify({ key, alarm }),
    }).then(J),

  health: () => fetch('/api/health').then(J),
  state: () => fetch('/api/state', { headers: H() }).then(J),

  chat: (message, lang, conversationId, forceTriage = false, role = 'elder') =>
    fetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, lang, conversation_id: conversationId,
                             force_triage: forceTriage, role }),
    }).then(J),

  voiceSos: (blob) => {
    const f = new FormData()
    f.append('file', blob, 'voice.wav')
    return fetch('/api/voice-sos', { method: 'POST', body: f }).then(J)
  },

  scan: (file, lang) => {
    const f = new FormData()
    f.append('file', file, file.name || 'scan.jpg')
    return fetch(`/api/scan?lang=${lang || 'en'}`, { method: 'POST', body: f }).then(J)
  },

  addMed: (name, time, note) =>
    fetch('/api/meds', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, time, note }) }).then(J),
  toggleMed: (name) =>
    fetch('/api/meds/taken', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }) }).then(J),
  deleteMed: (id) => fetch(`/api/meds/${id}`, { method: 'DELETE' }).then(J),

  saveProfile: (patch) =>
    fetch('/api/profile', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch) }).then(J),

  conversations: () => fetch('/api/conversations').then(J),
  conversation: (id) => fetch(`/api/conversations/${id}`).then(J),
  deleteConversation: (id) =>
    fetch(`/api/conversations/${id}`, { method: 'DELETE' }).then(J),

  readNotifications: () => fetch('/api/notifications/read', { method: 'POST' }).then(J),

  // ---- D3: fall detection + alarm ---------------------------------------
  fall: (confidence, source, features, lang) =>
    fetch('/api/fall', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confidence, source, features, lang }) }).then(J),

  analyzeThud: (blob, lang, autoAlarm = true) => {
    const f = new FormData()
    f.append('file', blob, 'clip.wav')
    return fetch(`/api/fall/analyze?lang=${lang || 'en'}&auto_alarm=${autoAlarm ? 1 : 0}`,
      { method: 'POST', body: f }).then(J)
  },

  alarm: () => fetch('/api/alarm').then(J),
  cancelAlarm: () => fetch('/api/alarm/cancel', { method: 'POST' }).then(J),
  helpAlarm: () => fetch('/api/alarm/help', { method: 'POST' }).then(J),
  sos: () => fetch('/api/sos', { method: 'POST' }).then(J),
  falls: () => fetch('/api/falls').then(J),

  // ---- D4: escalation record, hospitals, emergency card -------------------
  emergencies: () => fetch('/api/emergency').then(J),
  emergency: (id) => fetch(`/api/emergency/${id}`).then(J),
  logCall: (id, who) => fetch(`/api/emergency/${id}/call`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ who }) }).then(J),
  closeEmergency: (id) => fetch(`/api/emergency/${id}/close`, { method: 'POST' }).then(J),
  hospitals: (lat, lon) => fetch(`/api/hospitals${lat != null ? `?lat=${lat}&lon=${lon}` : ''}`).then(J),
  setLocation: (lat, lon, label) => fetch('/api/location', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lat, lon, label }) }).then(J),
  ecard: () => fetch('/api/ecard').then(J),

  // ---- D7: Sehat Board ----------------------------------------------------
  sehat: () => fetch('/api/sehat').then(J),
  logVitals: (payload) => fetch('/api/vitals', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(J),
  vitals: (days) => fetch(`/api/vitals?days=${days || 30}`).then(J),
  board: () => fetch('/api/board').then(J),

  // ---- D6: daily companion check-ins -------------------------------------
  checkinDue: (lang, force) =>
    fetch(`/api/checkin/due?lang=${lang || 'en'}${force ? '&force=1' : ''}`)
      .then(J),
  checkinAnswer: (kind, lang, answers) =>
    fetch('/api/checkin/answer', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, lang, answers }),
    }).then(J),
  checkinSkip: (kind, lang) =>
    fetch('/api/checkin/skip', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, lang }),
    }).then(J),
  checkins: (limit) => fetch(`/api/checkins?limit=${limit || 30}`).then(J),
  setCheckinSchedule: (patch) => fetch('/api/checkin/schedule', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }).then(J),
  dailySummary: () => fetch('/api/summary/daily').then(J),
  pushDailySummary: () => fetch('/api/summary/daily/push', {
    method: 'POST' }).then(J),

  // ---- D5: family monitor dashboard -------------------------------------
  transcribe: (blob) => {
    const f = new FormData()
    f.append('file', blob, 'voice.wav')
    return fetch('/api/transcribe', { method: 'POST', body: f }).then(J)
  },

  monitor: () => fetch('/api/monitor').then(J),
  ackMonitor: (by = 'family') =>
    fetch('/api/monitor/ack', {
      method: 'POST', headers: JH(),
      body: JSON.stringify({ by }),
    }).then(J),
}
