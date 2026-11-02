import { useState } from 'react'

/* Left rail: brand, New chat, conversation history, quick panels, user chip.
   Layout language is borrowed from ChatGPT; content is Saavren's. */

export default function Sidebar({
  t, conversations, activeId, onSelect, onNew, onRename, onDelete,
  unread, onOpenPanel, onOpenSettings, onToggleTheme, theme, profile, collapsed,
}) {
  const [editing, setEditing] = useState(null)
  const [draft, setDraft] = useState('')

  const commit = (c) => {
    if (draft.trim()) onRename(c.id, draft.trim())
    setEditing(null)
  }

  return (
    <aside className={'sidebar' + (collapsed ? ' collapsed' : '')}>
      <div className="brand">
        <div className="mark">S</div>
        <div>
          <b>Saavren</b>
          <small>akela nahi</small>
        </div>
      </div>

      <button className="sb-btn primary" onClick={onNew}>
        <span className="ico">✎</span> {t('new_chat')}
      </button>

      <div className="sb-scroll">
        {conversations.length > 0 && (
          <div className="sb-label">{t('history')}</div>
        )}
        {conversations.map((c) => (
          <div
            key={c.id}
            className={'conv' + (c.id === activeId ? ' active' : '')}
            onClick={() => onSelect(c.id)}
            title={c.title}
          >
            {editing === c.id ? (
              <input
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={() => commit(c)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commit(c)
                  if (e.key === 'Escape') setEditing(null)
                }}
                style={{ flex: 1, border: '1px solid var(--border)', borderRadius: 6,
                         background: 'var(--panel)', color: 'var(--text)', padding: '2px 6px' }}
              />
            ) : (
              <>
                <span className="t">{c.title || t('new_chat_title')}</span>
                <button
                  className="p"
                  title={t('rename')}
                  onClick={(e) => { e.stopPropagation(); setDraft(c.title); setEditing(c.id) }}
                >✎</button>
                <button
                  className="x"
                  title={t('delete')}
                  onClick={(e) => { e.stopPropagation(); onDelete(c.id) }}
                >🗑</button>
              </>
            )}
          </div>
        ))}
      </div>

      <div className="sb-label">{t('activity')}</div>
      <button className="sb-btn" onClick={() => onOpenPanel('meds')}>
        <span className="ico">💊</span> {t('medicines')}
      </button>
      <button className="sb-btn" onClick={() => onOpenPanel('health')}>
        <span className="ico">❤️</span> {t('health')}
      </button>
      <button className="sb-btn" onClick={() => onOpenPanel('activity')}>
        <span className="ico">📈</span> {t('activity')}
      </button>
      <button className="sb-btn" onClick={() => onOpenPanel('notifications')}>
        <span className="ico">🔔</span> {t('notifications')}
        {unread > 0 && <span className="badge">{unread}</span>}
      </button>

      <div className="sb-foot">
        <button className="sb-btn" onClick={onOpenSettings}>
          <span className="ico">⚙️</span> {t('settings')}
        </button>
        <button className="sb-btn" onClick={onToggleTheme}>
          <span className="ico">{theme === 'dark' ? '☀️' : '🌙'}</span>
          {theme === 'dark' ? t('theme_light') : t('theme_dark')}
        </button>
        <div className="user-chip" onClick={onOpenSettings}>
          <div className="avatar">{(profile?.name || 'S').slice(0, 1)}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13.5, fontWeight: 600 }}>{profile?.name || '—'}</div>
            <div style={{ fontSize: 11.5, color: 'var(--muted)' }}>{t('monitor')}</div>
          </div>
        </div>
      </div>
    </aside>
  )
}
