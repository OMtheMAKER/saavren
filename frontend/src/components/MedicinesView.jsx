import { useState } from 'react'

/**
 * Medicines — its own screen, deliberately not the Health dashboard.
 *
 * Health is the Sehat Board: body profile, BMI, vitals and the weekly points
 * board. This is the medicine cabinet: what is due today, what has been
 * taken, and adding or removing something from the list.
 */
export default function MedicinesView({ t, state, busy, onAdd, onToggle, onDelete }) {
  const meds = state?.meds || []
  const [name, setName] = useState('')
  const [time, setTime] = useState('09:00')
  const [note, setNote] = useState('')

  const taken = meds.filter((m) => m.taken).length
  const sorted = [...meds].sort((a, b) =>
    String(a.time || '').localeCompare(String(b.time || '')))

  async function submit(e) {
    e.preventDefault()
    const nm = name.trim()
    if (!nm) return
    const ok = await onAdd(nm, time, note.trim())
    if (ok) { setName(''); setNote('') }
  }

  return (
    <div className="view">
      <div className="card">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <b>{t('meds_today')}</b>
          <span className="chip">{t('doses_today', { n: taken, m: meds.length })}</span>
        </div>

        <div style={{ marginTop: 10 }}>
          {sorted.length === 0 && <div className="muted small">{t('no_meds')}</div>}

          {sorted.map((m) => (
            <div className="item" key={m.id}>
              <span className="small muted" style={{ width: 48, flex: 'none' }}>
                {m.time || '—'}
              </span>
              <span className="grow">
                <b style={{ textDecoration: m.taken ? 'line-through' : 'none' }}>
                  {m.name}
                </b>
                {m.note ? <div className="small muted">{m.note}</div> : null}
              </span>
              <button className={'btn small ' + (m.taken ? '' : 'ghost')}
                      disabled={busy} onClick={() => onToggle(m.name)}>
                {m.taken ? '✓ ' + t('taken') : t('mark_taken')}
              </button>
              <button className="iconbtn" title={t('delete')} disabled={busy}
                      onClick={() => onDelete(m.id)}>🗑</button>
            </div>
          ))}
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <b>{t('add_med')}</b>
        <form onSubmit={submit} className="col" style={{ marginTop: 10 }}>
          <input className="inp" value={name} onChange={(e) => setName(e.target.value)}
                 placeholder={t('med_name')} required />
          <div className="row">
            <input className="inp" type="time" value={time} title={t('med_time')}
                   aria-label={t('med_time')}
                   onChange={(e) => setTime(e.target.value)} style={{ width: 130 }} />
            <input className="inp grow" value={note}
                   onChange={(e) => setNote(e.target.value)}
                   placeholder={t('med_note')} />
          </div>
          <button className="btn" type="submit" disabled={busy || !name.trim()}>
            {t('add_med')}
          </button>
        </form>
      </div>
    </div>
  )
}
