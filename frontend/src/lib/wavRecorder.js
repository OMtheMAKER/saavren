/* Mic capture. The browser encodes straight to 16 kHz mono PCM WAV, so the
   elder's Windows machine needs no ffmpeg installed. */

export async function startRecording(onLevel) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true },
  })
  const ctx = new (window.AudioContext || window.webkitAudioContext)()
  await ctx.resume().catch(() => {})
  const src = ctx.createMediaStreamSource(stream)
  const rate = ctx.sampleRate || 48000

  // down-sample to 16 kHz with a ScriptProcessor (universally supported)
  const target = 16000
  const bufSize = 4096
  const proc = ctx.createScriptProcessor(bufSize, 1, 1)
  const chunks = []
  let frames = 0

  proc.onaudioprocess = (e) => {
    const input = e.inputBuffer.getChannelData(0)
    if (onLevel) {
      let peak = 0
      for (let i = 0; i < input.length; i += 8) {
        const v = Math.abs(input[i]); if (v > peak) peak = v
      }
      onLevel(Math.min(1, peak * 1.6))
    }
    if (rate === target) {
      chunks.push(new Float32Array(input))
      frames += input.length
      return
    }
    const ratio = rate / target
    const outLen = Math.floor(input.length / ratio)
    const out = new Float32Array(outLen)
    for (let i = 0; i < outLen; i++) {
      const p = i * ratio
      const a = Math.floor(p), b = Math.min(input.length - 1, a + 1)
      out[i] = input[a] + (input[b] - input[a]) * (p - a)
    }
    chunks.push(out)
    frames += outLen
  }

  src.connect(proc)
  proc.connect(ctx.destination)   // required by some browsers to pump events

  function stop() {
    try { src.disconnect(); proc.disconnect() } catch (e) { /* already gone */ }
    stream.getTracks().forEach((t) => t.stop())
    ctx.close().catch(() => {})

    const all = new Float32Array(frames)
    let off = 0
    for (const c of chunks) { all.set(c, off); off += c.length }
    return { blob: encodeWav(all, target), sampleRate: target,
             seconds: frames / target, samples: all }
  }
  return { stop, ctx, stream }
}

export function encodeWav(samples, rate = 16000) {
  const n = samples.length
  const buf = new ArrayBuffer(44 + n * 2)
  const v = new DataView(buf)
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)) }
  str(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); str(8, 'WAVE')
  str(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true)
  v.setUint16(22, 1, true); v.setUint32(24, rate, true)
  v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true)
  str(36, 'data'); v.setUint32(40, n * 2, true)
  let o = 44
  for (let i = 0; i < n; i++, o += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return new Blob([buf], { type: 'audio/wav' })
}

/* ------------------------------------------------------------------ */
/* Browser speech-to-text — no API key, no server                      */
/* ------------------------------------------------------------------ */
const LANG_TAG = { hi: 'hi-IN', bn: 'bn-IN', ta: 'ta-IN', te: 'te-IN', mr: 'mr-IN',
  gu: 'gu-IN', es: 'es-ES', fr: 'fr-FR', en: 'en-US' }

export function browserAsr(lang) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition
  if (!SR) return Promise.reject(new Error('browser ASR unsupported — Chrome/Edge use karein'))
  const tries = [...new Set([LANG_TAG[lang] || 'en-US', 'en-US'])]
  return new Promise((resolve, reject) => {
    let i = 0
    function attempt() {
      const r = new SR()
      r.lang = tries[i]; r.interimResults = false; r.maxAlternatives = 1
      r.continuous = false
      let done = false
      const finish = (fn, arg) => {
        if (done) return
        done = true
        try { r.abort() } catch (e) { /* already stopped */ }
        fn(arg)
      }
      r.onresult = (e) => {
        const txt = e.results?.[0]?.[0]?.transcript || ''
        txt ? finish(resolve, txt) : finish(reject, new Error('awaz samajh nahi aayi'))
      }
      r.onerror = (e) => {
        const code = e.error || 'mic error'
        if (/language|network|service|audio-capture|no-speech/i.test(code)
            && i + 1 < tries.length) { i += 1; setTimeout(attempt, 250); return }
        finish(reject, new Error(
          /not-allowed/.test(code)
            ? 'mic permission nahi mili — browser ke 🔒 icon se mic allow karein'
            : code === 'network'
              ? 'browser ASR ke liye internet chahiye — likh kar bhej dein' : code))
      }
      r.onend = () => finish(reject, new Error('awaz nahi mili — thoda zor se boliye'))
      try { r.start() } catch (e) { finish(reject, new Error('mic start nahi hua')) }
    }
    attempt()
  })
}
