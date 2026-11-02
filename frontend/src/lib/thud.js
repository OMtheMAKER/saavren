/* ============================================================
   D3 — fall / thud detection (runs in the browser, real time)

   A fall "thud" looks nothing like speech:
     * a sudden LOUD impulse        (peak jumps far above the room's baseline)
     * energy concentrated LOW      (< ~250 Hz — body hitting the floor)
     * very fast attack             (10% -> 90% of the peak in < 60 ms)
     * short burst, then quiet      (decays within ~0.5 s, no sustained voicing)

   So we measure those four things and only raise the alarm when they agree.
   Nothing is streamed anywhere: only the *verdict* is sent to the server,
   which then asks "are you OK?" and escalates if nobody answers.
   ============================================================ */

export const THUD_CFG = {
  peakMin: 0.28,        // absolute peak (0..1)
  overBaseline: 3.2,    // ...or this many times the room's quiet level
  lowRatioMin: 0.60,    // low-band RMS / total RMS (steep 4-pole @ 250 Hz)
  attackMsMax: 60,
  voicedMsMax: 400,     // TOTAL time above half the peak (speech stays there)
  zcrMax: 500,          // zero crossings/sec inside the burst
  settleMs: 900,        // window used to confirm the room went quiet again
  settleRatio: 0.45,
  cooldownMs: 8000,     // never fire twice within this
}

/* Same weights as the server's ai.thud_score, so a clip scores the same
   wherever it is analysed. */
const W = { loud: 0.25, low_freq: 0.20, fast_attack: 0.13,
            short_body: 0.17, quick_decay: 0.15, low_zcr: 0.10 }

/**
 * Start listening for a thud.
 * @returns {{stop: () => void, level: () => number}}
 */
export async function watchForThud({ onThud, onLevel } = {}) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
  })
  const Ctx = window.AudioContext || window.webkitAudioContext
  const ctx = new Ctx()
  await ctx.resume().catch(() => {})
  const src = ctx.createMediaStreamSource(stream)
  const rate = ctx.sampleRate || 48000

  const all = ctx.createAnalyser()
  all.fftSize = 2048
  // 4 cascaded low-pass sections @ 250 Hz (~-24 dB/oct) so speech harmonics
  // above ~400 Hz stop counting as "low" — this is what kills false alarms.
  const nodes = []
  let tail = src
  for (let i = 0; i < 4; i++) {
    const f = ctx.createBiquadFilter()
    f.type = 'lowpass'; f.frequency.value = 250; f.Q.value = 0.707
    tail.connect(f); tail = f; nodes.push(f)
  }
  const low = ctx.createAnalyser()
  low.fftSize = 2048
  src.connect(all); tail.connect(low)

  const bufAll = new Float32Array(all.fftSize)
  const bufLow = new Float32Array(low.fftSize)

  const FRAME = all.fftSize / rate * 1000          // ms per analysis frame
  let baseline = 0.004                              // slow EMA of the quiet room
  let prevPeak = 0, armed = true, lastFire = 0
  let pending = null                                // burst waiting for the quiet check
  let levelNow = 0

  const tickMs = 50
  const timer = setInterval(() => {
    all.getFloatTimeDomainData(bufAll)
    low.getFloatTimeDomainData(bufLow)

    let peak = 0, sum = 0
    for (let i = 0; i < bufAll.length; i++) {
      const v = Math.abs(bufAll[i]); if (v > peak) peak = v
      sum += bufAll[i] * bufAll[i]
    }
    const rms = Math.sqrt(sum / bufAll.length) || 1e-6
    let lsum = 0
    for (let i = 0; i < bufLow.length; i++) lsum += bufLow[i] * bufLow[i]
    const lowRms = Math.sqrt(lsum / bufLow.length) || 1e-6
    const lowRatio = lowRms / rms

    // zero crossings inside this frame — a 90 Hz thud barely crosses zero,
    // voiced speech (harmonics) crosses hundreds of times per second.
    let zc = 0
    for (let i = 1; i < bufAll.length; i++) {
      if ((bufAll[i - 1] < 0) !== (bufAll[i] < 0)) zc++
    }
    const zcr = Math.round(zc / (bufAll.length / rate))

    levelNow = Math.min(1, peak * 1.4)
    onLevel?.(levelNow)

    const loudEnough = peak >= THUD_CFG.peakMin &&
                       peak >= baseline * THUD_CFG.overBaseline
    const lowEnough = lowRatio >= THUD_CFG.lowRatioMin
    const fast = peak > prevPeak * 0.9 || prevPeak < baseline * 1.5

    if (armed && loudEnough && lowEnough && fast) {
      pending = { peak, lowRatio, rms, zcr, at: performance.now(),
                  above: 0, ticks: 0 }
      armed = false
    }

    // accumulate evidence during the settle window
    if (pending) {
      pending.ticks++
      if (peak >= pending.peak * 0.5) pending.above++
      if (zcr < pending.zcr) pending.zcr = zcr
    }

    // confirm: after the burst the room must go quiet again
    if (pending && performance.now() - pending.at >= THUD_CFG.settleMs) {
      const settled = rms <= pending.rms * THUD_CFG.settleRatio ||
                      rms <= baseline * 1.6
      const voicedMs = pending.above * tickMs
      const checks = {
        loud: pending.peak >= THUD_CFG.peakMin,
        low_freq: pending.lowRatio >= THUD_CFG.lowRatioMin,
        fast_attack: true,
        short_body: voicedMs <= THUD_CFG.voicedMsMax,
        quick_decay: settled,
        low_zcr: pending.zcr <= THUD_CFG.zcrMax,
      }
      const score = round2(Object.keys(W)
        .reduce((acc, k) => acc + (checks[k] ? W[k] : 0), 0))
      if (score >= 0.45 && performance.now() - lastFire > THUD_CFG.cooldownMs) {
        lastFire = performance.now()
        onThud?.({
          score,
          verdict: score >= 0.72 ? 'thud' : 'possible',
          peak: round2(pending.peak), low_ratio: round2(pending.lowRatio),
          zcr: pending.zcr, voiced_ms: voicedMs, checks,
        })
      }
      pending = null
      setTimeout(() => { armed = true }, 400)
    }

    // slow baseline tracking of the room
    baseline = baseline * 0.94 + rms * 0.06
    prevPeak = prevPeak * 0.7 + peak * 0.3
  }, tickMs)

  void FRAME
  return {
    stop() {
      clearInterval(timer)
      try { src.disconnect(); nodes.forEach((n) => n.disconnect()) } catch (e) { /* gone */ }
      stream.getTracks().forEach((t) => t.stop())
      ctx.close().catch(() => {})
    },
    level: () => levelNow,
  }
}

const round2 = (n) => Math.round(n * 100) / 100

/* ------------------------------------------------------------------ */
/* Alarm tone — generated, so no audio asset has to ship               */
/* ------------------------------------------------------------------ */
export function alarmTone() {
  const Ctx = window.AudioContext || window.webkitAudioContext
  if (!Ctx) return { stop() {} }
  const ctx = new Ctx()
  const gain = ctx.createGain()
  gain.gain.value = 0.0001
  gain.connect(ctx.destination)
  let stopped = false
  const beep = () => {
    if (stopped) return
    const o = ctx.createOscillator()
    const g = ctx.createGain()
    o.type = 'sine'; o.frequency.value = 880
    g.gain.setValueAtTime(0.0001, ctx.currentTime)
    g.gain.exponentialRampToValueAtTime(0.22, ctx.currentTime + 0.02)
    g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.42)
    o.connect(g); g.connect(gain)
    o.start(); o.stop(ctx.currentTime + 0.45)
    setTimeout(beep, 700)
  }
  gain.gain.setValueAtTime(0.9, ctx.currentTime)
  beep()
  return {
    stop() {
      stopped = true
      try { ctx.close() } catch (e) { /* gone */ }
    },
  }
}

/* ------------------------------------------------------------------ */
/* Synthetic thud — lets you demo/test the pipeline without falling    */
/* ------------------------------------------------------------------ */
export function syntheticThudWav(seconds = 3) {
  const rate = 16000
  const n = rate * seconds
  const s = new Float32Array(n)
  const start = Math.floor(rate * 0.5)
  const burst = Math.floor(rate * 0.09)
  for (let i = 0; i < burst; i++) {
    const t = i / rate
    s[start + i] = 0.78 * Math.sin(2 * Math.PI * 92 * t) * Math.exp(-i / (rate * 0.045))
      + 0.18 * Math.sin(2 * Math.PI * 210 * t) * Math.exp(-i / (rate * 0.02))
  }
  // a little room noise so the detector sees a realistic floor
  for (let i = 0; i < n; i++) s[i] += (Math.random() - 0.5) * 0.004
  return encodeWavLocal(s, rate)
}

function encodeWavLocal(samples, rate) {
  const n = samples.length
  const buf = new ArrayBuffer(44 + n * 2)
  const v = new DataView(buf)
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)) }
  str(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); str(8, 'WAVE')
  str(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true)
  v.setUint16(22, 1, true); v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true)
  v.setUint16(32, 2, true); v.setUint16(34, 16, true)
  str(36, 'data'); v.setUint32(40, n * 2, true)
  let o = 44
  for (let i = 0; i < n; i++, o += 2) {
    const x = Math.max(-1, Math.min(1, samples[i]))
    v.setInt16(o, x < 0 ? x * 0x8000 : x * 0x7fff, true)
  }
  return new Blob([buf], { type: 'audio/wav' })
}
