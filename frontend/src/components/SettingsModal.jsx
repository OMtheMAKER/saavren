import { LANGS } from '../lib/i18n'

export default function SettingsModal({
  t, onClose, theme, setTheme, lang, setLang, voiceOut, setVoiceOut,
  persona, setPersona, health,
}) {
  return (
    <div className="modal" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <h3>⚙️ {t('settings')}</h3>
        <div className="sub">Saavren · v{health?.version || '—'}</div>

        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>{t('theme')}</div>
        <div className="seg" style={{ marginBottom: 16 }}>
          <button className={theme === 'light' ? 'on' : ''} onClick={() => setTheme('light')}>
            ☀️ {t('theme_light')}
          </button>
          <button className={theme === 'dark' ? 'on' : ''} onClick={() => setTheme('dark')}>
            🌙 {t('theme_dark')}
          </button>
        </div>

        <div className="field">
          <label>{t('language')}</label>
          <select value={lang} onChange={(e) => setLang(e.target.value)}>
            {LANGS.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
        </div>

        <div style={{ fontSize: 13, fontWeight: 700, margin: '14px 0 6px' }}>{t('persona')}</div>
        <div className="seg" style={{ marginBottom: 16 }}>
          {[['friend', 'persona_friend'], ['formal', 'persona_formal'], ['calm', 'persona_calm']]
            .map(([k, label]) => (
              <button key={k} className={persona === k ? 'on' : ''} onClick={() => setPersona(k)}>
                {t(label)}
              </button>
            ))}
        </div>

        <div className="row" style={{ borderTop: '1px solid var(--border)' }}>
          <div className="grow">
            <div className="t">{t('voice_out')}</div>
            <div className="s">🎙️ tap ke baad hi bolegi</div>
          </div>
          <button className={'pill' + (voiceOut ? ' on' : '')} onClick={() => setVoiceOut(!voiceOut)}>
            {voiceOut ? t('on') : t('off')}
          </button>
        </div>

        <div style={{ marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
          <div className="kv"><span>{t('model')}</span><span>{health?.baseten_model || '—'} · Baseten → Groq</span></div>
          <div className="kv"><span>{t('source')}</span><span>{health?.provider_order?.join(' → ') || '—'}</span></div>
          <div className="kv"><span>ASR</span><span>{health?.asr_chain?.join(' → ') || health?.asr_mode || '—'}{health && !health.asr_chain?.includes('mms') && (
            <span style={{ opacity: 0.55 }}> — MMS needs HF token</span>
          )}</span></div>
          <div className="kv"><span>ffmpeg</span><span>{health ? (health.ffmpeg_ready ? 'available' : 'not needed (browser WAV)') : '—'}</span></div>
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 18 }}>
          <button className="btn" style={{ flex: 1 }} onClick={onClose}>{t('close')}</button>
        </div>
      </div>
    </div>
  )
}
