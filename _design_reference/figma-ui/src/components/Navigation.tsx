import React, { useState } from 'react'

type Screen = 'home' | 'character' | 'story' | 'storylab' | 'messaging' | 'notifications' | 'creation'
type Gem = 'sapphire' | 'emerald' | 'amethyst' | 'ruby' | 'gold' | 'obsidian'

interface NavProps {
  active: Screen
  onNavigate: (s: Screen) => void
  gem: Gem
  onGemChange: (g: Gem) => void
  lightMode: boolean
  onToggleLight: () => void
}

const GEMS: { id: Gem; label: string; color: string }[] = [
  { id: 'sapphire',  label: 'Sapphire',  color: '#4f8ef7' },
  { id: 'emerald',   label: 'Emerald',   color: '#2dc896' },
  { id: 'amethyst',  label: 'Amethyst',  color: '#9b6ef2' },
  { id: 'ruby',      label: 'Ruby',      color: '#e05570' },
  { id: 'gold',      label: 'Gold',      color: '#cc9f44' },
  { id: 'obsidian',  label: 'Obsidian',  color: '#b0b8c8' },
]

const NAV: { id: Screen; label: string; badge?: number }[] = [
  { id: 'home',          label: 'Home' },
  { id: 'character',     label: 'Characters' },
  { id: 'storylab',      label: 'StoryLab' },
  { id: 'story',         label: 'Stories' },
  { id: 'messaging',     label: 'Messages', badge: 3 },
  { id: 'notifications', label: 'Notifications', badge: 7 },
  { id: 'creation',      label: 'Create Character' },
]

function NavIcon({ id, size = 20 }: { id: Screen; size?: number }) {
  const s = size
  const icons: Record<Screen, React.ReactElement> = {
    home: (
      <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 9.5L12 3l9 6.5V21a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9.5z"/>
        <path d="M9 22V12h6v10"/>
      </svg>
    ),
    character: (
      <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="8" r="4"/>
        <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>
      </svg>
    ),
    storylab: (
      <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2L2 7l10 5 10-5-10-5z"/>
        <path d="M2 17l10 5 10-5"/>
        <path d="M2 12l10 5 10-5"/>
      </svg>
    ),
    story: (
      <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
        <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
      </svg>
    ),
    messaging: (
      <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </svg>
    ),
    notifications: (
      <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
        <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
      </svg>
    ),
    creation: (
      <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <path d="M12 8v8M8 12h8"/>
      </svg>
    ),
  }
  return icons[id]
}

export default function Navigation({ active, onNavigate, gem, onGemChange, lightMode, onToggleLight }: NavProps) {
  const [showGems, setShowGems] = useState(false)
  const [tooltip, setTooltip] = useState<string | null>(null)

  return (
    <nav
      style={{
        width: 64,
        minWidth: 64,
        background: 'var(--surface)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '20px 0',
        gap: 0,
        position: 'relative',
        zIndex: 10,
        flexShrink: 0,
      }}
    >
      {/* Logo */}
      <button
        onClick={() => onNavigate('home')}
        style={{
          width: 36,
          height: 36,
          borderRadius: 10,
          background: 'var(--accent)',
          border: 'none',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: 28,
          flexShrink: 0,
          boxShadow: '0 2px 12px var(--accent-glow)',
        }}
        onMouseEnter={() => setTooltip('Ficshon')}
        onMouseLeave={() => setTooltip(null)}
      >
        <span style={{ fontFamily: 'var(--font-serif)', fontWeight: 700, fontSize: 16, color: '#fff', lineHeight: 1 }}>F</span>
      </button>

      {/* Nav items */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, width: '100%', alignItems: 'center', flex: 1 }}>
        {NAV.slice(0, 6).map(item => {
          const isActive = active === item.id
          return (
            <div key={item.id} style={{ position: 'relative', width: '100%', display: 'flex', justifyContent: 'center' }}>
              <button
                onClick={() => onNavigate(item.id)}
                onMouseEnter={() => setTooltip(item.label)}
                onMouseLeave={() => setTooltip(null)}
                style={{
                  width: 40,
                  height: 40,
                  borderRadius: 10,
                  border: 'none',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  position: 'relative',
                  background: isActive ? 'var(--accent-soft)' : 'transparent',
                  color: isActive ? 'var(--accent)' : 'var(--text-3)',
                  transition: 'all 150ms ease',
                }}
                className="hover:!bg-[var(--elevated)] hover:!text-[var(--text-2)]"
              >
                <NavIcon id={item.id} />
                {item.badge && !isActive && (
                  <span style={{
                    position: 'absolute',
                    top: 6,
                    right: 6,
                    width: 7,
                    height: 7,
                    borderRadius: '50%',
                    background: 'var(--accent)',
                    border: '1.5px solid var(--surface)',
                  }} />
                )}
                {isActive && (
                  <span style={{
                    position: 'absolute',
                    left: -8,
                    top: '50%',
                    transform: 'translateY(-50%)',
                    width: 3,
                    height: 18,
                    borderRadius: '0 3px 3px 0',
                    background: 'var(--accent)',
                  }} />
                )}
              </button>
              {/* Tooltip */}
              {tooltip === item.label && (
                <div style={{
                  position: 'absolute',
                  left: 52,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'var(--overlay)',
                  border: '1px solid var(--border-md)',
                  borderRadius: 8,
                  padding: '6px 12px',
                  whiteSpace: 'nowrap',
                  fontSize: 13,
                  fontWeight: 500,
                  color: 'var(--text)',
                  pointerEvents: 'none',
                  zIndex: 100,
                  boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
                }}>
                  {item.label}
                  {item.badge && (
                    <span style={{
                      marginLeft: 8,
                      background: 'var(--accent-soft)',
                      color: 'var(--accent)',
                      borderRadius: 10,
                      padding: '1px 7px',
                      fontSize: 11,
                      fontFamily: 'var(--font-mono)',
                    }}>{item.badge}</span>
                  )}
                </div>
              )}
            </div>
          )
        })}

        <div style={{ margin: '16px 0', width: 32, height: 1, background: 'var(--border)' }} />

        {/* Create character */}
        <div style={{ position: 'relative', width: '100%', display: 'flex', justifyContent: 'center' }}>
          <button
            onClick={() => onNavigate('creation')}
            onMouseEnter={() => setTooltip('Create Character')}
            onMouseLeave={() => setTooltip(null)}
            style={{
              width: 40,
              height: 40,
              borderRadius: 10,
              border: '1px dashed var(--border-md)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: active === 'creation' ? 'var(--accent-soft)' : 'transparent',
              color: active === 'creation' ? 'var(--accent)' : 'var(--text-3)',
            }}
          >
            <NavIcon id="creation" />
          </button>
          {tooltip === 'Create Character' && (
            <div style={{
              position: 'absolute',
              left: 52,
              top: '50%',
              transform: 'translateY(-50%)',
              background: 'var(--overlay)',
              border: '1px solid var(--border-md)',
              borderRadius: 8,
              padding: '6px 12px',
              whiteSpace: 'nowrap',
              fontSize: 13,
              fontWeight: 500,
              color: 'var(--text)',
              pointerEvents: 'none',
              zIndex: 100,
              boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
            }}>Create Character</div>
          )}
        </div>
      </div>

      {/* Bottom controls */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'center' }}>
        {/* Light/dark toggle */}
        <button
          onClick={onToggleLight}
          onMouseEnter={() => setTooltip(lightMode ? 'Dark Mode' : 'Light Mode')}
          onMouseLeave={() => setTooltip(null)}
          style={{
            width: 40,
            height: 40,
            borderRadius: 10,
            border: 'none',
            cursor: 'pointer',
            background: 'transparent',
            color: 'var(--text-3)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {lightMode ? (
            <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
            </svg>
          ) : (
            <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="5"/>
              <line x1="12" y1="1" x2="12" y2="3"/>
              <line x1="12" y1="21" x2="12" y2="23"/>
              <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
              <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
              <line x1="1" y1="12" x2="3" y2="12"/>
              <line x1="21" y1="12" x2="23" y2="12"/>
              <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
              <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
            </svg>
          )}
        </button>

        {/* Gem picker */}
        <div style={{ position: 'relative' }}>
          <button
            onClick={() => setShowGems(s => !s)}
            onMouseEnter={() => !showGems && setTooltip('Theme')}
            onMouseLeave={() => setTooltip(null)}
            style={{
              width: 28,
              height: 28,
              borderRadius: '50%',
              background: 'var(--accent)',
              border: '2px solid var(--surface)',
              cursor: 'pointer',
              boxShadow: '0 0 0 1px var(--accent-border)',
            }}
          />
          {showGems && (
            <div style={{
              position: 'absolute',
              bottom: 36,
              left: '50%',
              transform: 'translateX(-50%)',
              background: 'var(--overlay)',
              border: '1px solid var(--border-md)',
              borderRadius: 14,
              padding: '12px 10px',
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
              alignItems: 'center',
              zIndex: 200,
              boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
            }}>
              {GEMS.map(g => (
                <button
                  key={g.id}
                  title={g.label}
                  onClick={() => { onGemChange(g.id); setShowGems(false) }}
                  style={{
                    width: 22,
                    height: 22,
                    borderRadius: '50%',
                    background: g.color,
                    border: gem === g.id ? `2px solid ${g.color}` : '2px solid transparent',
                    cursor: 'pointer',
                    boxShadow: gem === g.id ? `0 0 0 1px rgba(255,255,255,0.3), 0 2px 8px ${g.color}55` : 'none',
                    outline: 'none',
                  }}
                />
              ))}
            </div>
          )}
        </div>

        {/* Avatar */}
        <div style={{ marginTop: 8 }}>
          <div
            onMouseEnter={() => setTooltip('Grace Fielding')}
            onMouseLeave={() => setTooltip(null)}
            style={{
              width: 32,
              height: 32,
              borderRadius: '50%',
              overflow: 'hidden',
              border: '2px solid var(--border-md)',
              cursor: 'pointer',
            }}
          >
            <img
              src="https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=64&h=64&fit=crop&auto=format"
              alt="Grace Fielding"
              style={{ width: '100%', height: '100%', objectFit: 'cover' }}
            />
          </div>
          {tooltip === 'Grace Fielding' && (
            <div style={{
              position: 'absolute',
              left: 52,
              bottom: 8,
              background: 'var(--overlay)',
              border: '1px solid var(--border-md)',
              borderRadius: 8,
              padding: '6px 12px',
              whiteSpace: 'nowrap',
              fontSize: 13,
              fontWeight: 500,
              color: 'var(--text)',
              pointerEvents: 'none',
              zIndex: 100,
              boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
            }}>Grace Fielding</div>
          )}
        </div>
      </div>
    </nav>
  )
}
