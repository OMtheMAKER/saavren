import { useEffect, useRef, useState } from 'react'
import { alarmTone } from '../lib/thud'

/**
 * D3 escalation alarm.
 * A thud (or the SOS button) raises this: the elder gets `grace` seconds to
 * say "I'm OK". No answer -> the server notifies family + doctor.
 */
export default function AlertOverlay({ alarm, remaining, t, onCancel, onHelp, onDone }) {
  const [left, setLeft] = useState(remaining)
  const tone = useRef(null)
  const alive = alarm && alarm.status === 'ringing'

  useEffect(() => {
    if (!alarm) return
    if (alarm.status === 'ringing') {
      tone.current = alarmTone()
      try { navigator.vibrate?.([400, 200, 400]) } catch (e) { /* ignore */ }
    }
    return () => { tone.current?.stop(); tone.current = null }
  }, [alarm?.id, alarm?.status])

  useEffect(() => {
    if (!alive) return
    setLeft(alarm.grace)
    const id = setInterval(() => setLeft((s) => Math.max(0, +(s - 0.1).toFixed(1))), 100)
    return () => clearInterval(id)
  }, [alive, alarm?.id, alarm?.grace])

  if (!alarm) return null
  const done = alarm.status !== 'ringing'
  const pct = alarm.grace ? Math.max(0, Math.min(1, left / alarm.grace)) : 0
  const deg = Math.round(pct * 360)

  return (
    <div className={'alarm' + (done ? ' done' : '')}>
      <div className="panel">
        {alive ? (
          <>
            <div className="ring" style={{ '--p': deg + 'deg' }}>
              <b>{Math.ceil(left)}</b>
            </div>
            <h2>{t('fall_title')}</h2>
            <p>{t('fall_sub')}</p>
            <div className="btns">
              <button className="btn ok" onClick={onCancel}>{t('im_ok')}</button>
              <button className="btn danger" onClick={onHelp}>{t('need_help')}</button>
            </div>
            <div className="rec" style={{ marginTop: 14 }}>
              <span className="dot" /> {t('mic_watch')}
            </div>
          </>
        ) : (
          <>
            <div style={{ fontSize: 44, marginBottom: 10 }}>
              {alarm.status === 'cancelled' ? '✅' : '🚨'}
            </div>
            <h2>{alarm.status === 'cancelled' ? t('im_ok') : t('emergency')}</h2>
            <p>{alarm.status === 'cancelled'
              ? t('fall_cancelled') : t('fall_escalated')}</p>
            <button className="btn wide" onClick={onDone}>{t('cancel')}</button>
          </>
        )}
      </div>
    </div>
  )
}
