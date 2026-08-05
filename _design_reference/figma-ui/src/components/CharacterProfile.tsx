import { useState } from 'react'

type NavigateFn = (s: 'home' | 'character' | 'story' | 'storylab' | 'messaging' | 'notifications' | 'creation') => void

interface Props {
  onNavigate: NavigateFn
}

const TIMELINE = [
  {
    id: 1,
    type: 'IC',
    title: 'A good breakfast is always vital.',
    body: 'The tomatoes came in heavy overnight. There is something about the weight of a ripe tomato in your palm — the way it yields just slightly — that tells you the season is turning.',
    image: 'https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=600&h=320&fit=crop&auto=format',
    time: '2 hours ago',
    likes: 47,
    replies: 12,
  },
  {
    id: 2,
    type: 'IC',
    title: 'The path to the coast is closed again.',
    body: "Three times this month. Whoever is rerouting the trail has not thought about where the water goes after heavy rain. I\'ll speak to the groundskeeper before it becomes a problem.",
    image: null,
    time: '3 days ago',
    likes: 31,
    replies: 8,
  },
  {
    id: 3,
    type: 'Story',
    title: 'The Weight of Morning Light — Chapter 3',
    body: 'He stood in the garden before dawn had properly broken, watching the light change over the sea cliff. The Chapter is available now.',
    image: 'https://images.unsplash.com/photo-1448375240586-882707db888b?w=600&h=280&fit=crop&auto=format',
    time: '1 week ago',
    likes: 189,
    replies: 44,
  },
]

const STORIES = [
  {
    title: 'The Weight of Morning Light',
    chapters: 3,
    words: '14,200',
    status: 'ongoing',
    cover: 'https://images.unsplash.com/photo-1448375240586-882707db888b?w=300&h=180&fit=crop&auto=format',
  },
  {
    title: 'Letters from the Cliff House',
    chapters: 1,
    words: '2,800',
    status: 'complete',
    cover: 'https://images.unsplash.com/photo-1499678329028-101435549a4e?w=300&h=180&fit=crop&auto=format',
  },
]

export default function CharacterProfile({ onNavigate }: Props) {
  const [tab, setTab] = useState<'timeline' | 'stories' | 'media' | 'relationships' | 'world'>('timeline')
  const [following, setFollowing] = useState(false)

  return (
    <div style={{ flex: 1, overflow: 'hidden auto', height: '100%' }} className="hide-scrollbar">
      {/* ── Cinematic cover ──────────────────────────────── */}
      <div style={{ position: 'relative', height: '72vh', minHeight: 480, maxHeight: 700 }}>
        <img
          src="https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1600&h=900&fit=crop&auto=format"
          alt="Pan — The Verdant Coast"
          style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
        />
        {/* gradient overlay */}
        <div className="cover-gradient" style={{ position: 'absolute', inset: 0 }} />

        {/* Character name overlay */}
        <div style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          padding: '0 48px 40px',
          display: 'flex',
          alignItems: 'flex-end',
          gap: 24,
        }}>
          <div>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              marginBottom: 8,
            }}>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                letterSpacing: '0.14em',
                textTransform: 'uppercase',
                color: 'rgba(255,255,255,0.6)',
              }}>
                Human · The Verdant Coast
              </span>
              <span style={{
                fontSize: 11,
                fontFamily: 'var(--font-mono)',
                color: 'rgba(45,200,150,0.9)',
                background: 'rgba(45,200,150,0.12)',
                border: '1px solid rgba(45,200,150,0.3)',
                borderRadius: 4,
                padding: '2px 8px',
                letterSpacing: '0.05em',
              }}>
                Identity Locked
              </span>
            </div>
            <h1 style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 'clamp(56px, 8vw, 96px)',
              fontWeight: 600,
              color: '#fff',
              lineHeight: 0.95,
              letterSpacing: '-0.02em',
              textShadow: '0 2px 40px rgba(0,0,0,0.4)',
            }}>
              Pan
            </h1>
          </div>
        </div>

        {/* Back button */}
        <button
          onClick={() => onNavigate('home')}
          style={{
            position: 'absolute',
            top: 24,
            left: 24,
            background: 'rgba(0,0,0,0.4)',
            backdropFilter: 'blur(8px)',
            border: '1px solid rgba(255,255,255,0.15)',
            borderRadius: 10,
            padding: '8px 14px',
            cursor: 'pointer',
            color: '#fff',
            fontSize: 13,
            fontWeight: 500,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 12H5M12 5l-7 7 7 7"/>
          </svg>
          Back
        </button>

        {/* Manage button */}
        <button style={{
          position: 'absolute',
          top: 24,
          right: 24,
          background: 'rgba(0,0,0,0.4)',
          backdropFilter: 'blur(8px)',
          border: '1px solid rgba(255,255,255,0.15)',
          borderRadius: 10,
          padding: '8px 16px',
          cursor: 'pointer',
          color: '#fff',
          fontSize: 13,
          fontWeight: 500,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}>
          <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 19.07a10 10 0 0 1 0-14.14"/>
          </svg>
          Manage
        </button>
      </div>

      {/* ── Profile info band ────────────────────────────── */}
      <div style={{
        padding: '28px 48px 0',
        display: 'flex',
        alignItems: 'flex-start',
        gap: 20,
      }}>
        {/* Avatar */}
        <div style={{
          width: 72,
          height: 72,
          borderRadius: 16,
          overflow: 'hidden',
          border: '3px solid var(--bg)',
          boxShadow: '0 0 0 1px var(--border-md), 0 4px 16px rgba(0,0,0,0.3)',
          flexShrink: 0,
          marginTop: -36,
        }}>
          <img
            src="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=144&h=144&fit=crop&auto=format"
            alt="Pan"
            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          />
        </div>

        {/* Stats */}
        <div style={{ flex: 1, display: 'flex', gap: 32, alignItems: 'center', paddingTop: 4 }}>
          {[
            { label: 'Posts', value: '2' },
            { label: 'Followers', value: '—' },
            { label: 'Stories', value: '2' },
            { label: 'Relationships', value: '4' },
          ].map(stat => (
            <div key={stat.label} style={{ textAlign: 'center' }}>
              <div style={{
                fontFamily: 'var(--font-serif)',
                fontSize: 22,
                fontWeight: 500,
                color: 'var(--text)',
                lineHeight: 1.2,
              }}>
                {stat.value}
              </div>
              <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                {stat.label}
              </div>
            </div>
          ))}
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', gap: 8, paddingTop: 4 }}>
          <button
            onClick={() => setFollowing(f => !f)}
            style={{
              background: following ? 'transparent' : 'var(--accent)',
              border: following ? '1px solid var(--border-md)' : 'none',
              borderRadius: 10,
              padding: '9px 20px',
              cursor: 'pointer',
              color: following ? 'var(--text-2)' : '#fff',
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            {following ? 'Following' : 'Follow'}
          </button>
          <button style={{
            background: 'var(--elevated)',
            border: '1px solid var(--border)',
            borderRadius: 10,
            padding: '9px 16px',
            cursor: 'pointer',
            color: 'var(--text-2)',
            fontSize: 13,
            fontWeight: 500,
          }}>
            Message
          </button>
        </div>
      </div>

      {/* Bio */}
      <div style={{ padding: '16px 48px 0', maxWidth: 560 }}>
        <p style={{ fontSize: 14, lineHeight: 1.65, color: 'var(--text-2)' }}>
          A man who tends his garden as carefully as he tends his words. Lives on the coast. Prefers mornings. Knows things he doesn't say.
        </p>
      </div>

      {/* ── Tabs ────────────────────────────────────────── */}
      <div style={{
        padding: '24px 48px 0',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        gap: 4,
      }}>
        {(['timeline', 'stories', 'media', 'relationships', 'world'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              fontSize: 13,
              fontWeight: 500,
              color: tab === t ? 'var(--text)' : 'var(--text-3)',
              padding: '8px 16px',
              borderBottom: `2px solid ${tab === t ? 'var(--accent)' : 'transparent'}`,
              textTransform: 'capitalize',
              marginBottom: -1,
            }}
          >
            {t}
          </button>
        ))}
      </div>

      {/* ── Content ─────────────────────────────────────── */}
      <div style={{ padding: '0 48px', display: 'flex', gap: 40 }}>
        <div style={{ flex: 1, minWidth: 0, maxWidth: 620 }}>
          {tab === 'timeline' && TIMELINE.map(item => (
            <article key={item.id} style={{ padding: '28px 0', borderBottom: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
                <span style={{
                  fontSize: 10,
                  fontFamily: 'var(--font-mono)',
                  color: item.type === 'IC' ? 'var(--accent)' : 'var(--text-3)',
                  background: item.type === 'IC' ? 'var(--accent-soft)' : 'var(--elevated)',
                  border: `1px solid ${item.type === 'IC' ? 'var(--accent-border)' : 'var(--border)'}`,
                  borderRadius: 4,
                  padding: '2px 6px',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                }}>
                  {item.type}
                </span>
                <span style={{ fontSize: 12, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>{item.time}</span>
              </div>
              <h3
                onClick={() => onNavigate('story')}
                style={{
                  fontFamily: 'var(--font-serif)',
                  fontSize: 21,
                  fontWeight: 500,
                  color: 'var(--text)',
                  marginBottom: 8,
                  lineHeight: 1.35,
                  cursor: 'pointer',
                }}
              >
                {item.title}
              </h3>
              <p style={{ fontSize: 14.5, lineHeight: 1.7, color: 'var(--text-2)', marginBottom: item.image ? 14 : 0 }}>
                {item.body}
              </p>
              {item.image && (
                <div style={{ borderRadius: 12, overflow: 'hidden', border: '1px solid var(--border)', cursor: 'pointer' }} onClick={() => onNavigate('story')}>
                  <img src={item.image} alt={item.title} style={{ width: '100%', height: 220, objectFit: 'cover', display: 'block' }} />
                </div>
              )}
              <div style={{ display: 'flex', gap: 16, marginTop: 14 }}>
                <span style={{ fontSize: 12, color: 'var(--text-3)', display: 'flex', alignItems: 'center', gap: 5 }}>
                  <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>
                  {item.likes}
                </span>
                <span style={{ fontSize: 12, color: 'var(--text-3)', display: 'flex', alignItems: 'center', gap: 5 }}>
                  <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                  {item.replies}
                </span>
              </div>
            </article>
          ))}

          {tab === 'stories' && (
            <div style={{ padding: '28px 0', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              {STORIES.map(s => (
                <button
                  key={s.title}
                  onClick={() => onNavigate('story')}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, textAlign: 'left' }}
                >
                  <div style={{
                    border: '1px solid var(--border)',
                    borderRadius: 14,
                    overflow: 'hidden',
                    background: 'var(--surface)',
                  }}>
                    <div style={{ height: 130, overflow: 'hidden' }}>
                      <img src={s.cover} alt={s.title} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    </div>
                    <div style={{ padding: 14 }}>
                      <div style={{
                        fontSize: 10,
                        fontFamily: 'var(--font-mono)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.08em',
                        color: s.status === 'ongoing' ? 'var(--accent)' : 'var(--text-3)',
                        marginBottom: 6,
                      }}>
                        {s.status}
                      </div>
                      <div style={{ fontFamily: 'var(--font-serif)', fontSize: 15, fontWeight: 500, color: 'var(--text)', lineHeight: 1.4, marginBottom: 8 }}>
                        {s.title}
                      </div>
                      <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
                        {s.chapters} ch · {s.words} words
                      </div>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}

          {tab === 'media' && (
            <div style={{ padding: '28px 0' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 4 }}>
                {[
                  'https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=300&h=300&fit=crop&auto=format',
                  'https://images.unsplash.com/photo-1448375240586-882707db888b?w=300&h=300&fit=crop&auto=format',
                  'https://images.unsplash.com/photo-1499678329028-101435549a4e?w=300&h=300&fit=crop&auto=format',
                  'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=300&h=300&fit=crop&auto=format',
                  'https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?w=300&h=300&fit=crop&auto=format',
                  'https://images.unsplash.com/photo-1470770841072-f978cf4d019e?w=300&h=300&fit=crop&auto=format',
                ].map((src, i) => (
                  <div key={i} style={{ aspectRatio: '1', overflow: 'hidden', borderRadius: 4, cursor: 'pointer' }}>
                    <img src={src} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  </div>
                ))}
              </div>
            </div>
          )}

          {tab === 'relationships' && (
            <div style={{ padding: '28px 0', display: 'flex', flexDirection: 'column', gap: 12 }}>
              {[
                { name: 'Summer Vael', type: 'Ally', note: 'Met on the eastern shore. Trust, slowly given.', avatar: 'https://images.unsplash.com/photo-1488716820095-cbe80883c496?w=64&h=64&fit=crop&auto=format' },
                { name: 'Shadow', type: 'Ambiguous', note: 'Known of each other. Not yet met.', avatar: 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=64&h=64&fit=crop&auto=format' },
                { name: 'Lyra Ashwind', type: 'Friend', note: 'Correspondence across three years.', avatar: 'https://images.unsplash.com/photo-1531746020798-e6953c6e8e04?w=64&h=64&fit=crop&auto=format' },
              ].map(rel => (
                <div key={rel.name} style={{
                  display: 'flex',
                  gap: 14,
                  padding: '16px 18px',
                  background: 'var(--surface)',
                  border: '1px solid var(--border)',
                  borderRadius: 12,
                  alignItems: 'flex-start',
                }}>
                  <div style={{ width: 40, height: 40, borderRadius: '50%', overflow: 'hidden', border: '1.5px solid var(--border-md)', flexShrink: 0 }}>
                    <img src={rel.avatar} alt={rel.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  </div>
                  <div>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
                      <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{rel.name}</span>
                      <span style={{
                        fontSize: 10,
                        fontFamily: 'var(--font-mono)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.06em',
                        color: 'var(--text-3)',
                        background: 'var(--elevated)',
                        border: '1px solid var(--border)',
                        borderRadius: 4,
                        padding: '2px 6px',
                      }}>{rel.type}</span>
                    </div>
                    <p style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.5 }}>{rel.note}</p>
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === 'world' && (
            <div style={{ padding: '28px 0' }}>
              <div style={{
                padding: '24px',
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: 16,
                marginBottom: 16,
              }}>
                <h4 style={{ fontFamily: 'var(--font-serif)', fontSize: 18, fontWeight: 500, color: 'var(--text)', marginBottom: 10 }}>The Verdant Coast</h4>
                <p style={{ fontSize: 14, lineHeight: 1.7, color: 'var(--text-2)' }}>
                  A temperate stretch of coastline where farming communities coexist with older mysteries. Pan's home is a stone farmhouse two miles from the nearest village, set above a working garden that produces more than he can eat alone.
                </p>
              </div>
              <div style={{
                padding: '24px',
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: 16,
              }}>
                <h4 style={{ fontFamily: 'var(--font-serif)', fontSize: 18, fontWeight: 500, color: 'var(--text)', marginBottom: 10 }}>Lore Notes</h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {['Has never spoken of his parents.', 'Carries a leather journal, always.', 'Knows the name of every plant that grows in the garden, and several that don\'t.', 'Does not lock his doors.'].map((note, i) => (
                    <div key={i} style={{ display: 'flex', gap: 10, fontSize: 13.5, color: 'var(--text-2)', lineHeight: 1.55 }}>
                      <span style={{ color: 'var(--text-3)', flexShrink: 0 }}>—</span>
                      {note}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Right aside */}
        <div style={{ width: 220, flexShrink: 0, paddingTop: 28 }}>
          <div style={{
            padding: '18px',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 14,
            marginBottom: 16,
          }}>
            <h4 style={{ fontSize: 11, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-3)', marginBottom: 12 }}>
              Character Info
            </h4>
            {[
              { label: 'Created', value: 'July 2025' },
              { label: 'Status', value: 'Active' },
              { label: 'Visibility', value: 'Public' },
              { label: 'Realm', value: 'The Verdant Coast' },
              { label: 'Age', value: 'Mid-30s (est.)' },
            ].map(row => (
              <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 9 }}>
                <span style={{ fontSize: 12, color: 'var(--text-3)' }}>{row.label}</span>
                <span style={{ fontSize: 12, color: 'var(--text-2)', fontWeight: 500 }}>{row.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
