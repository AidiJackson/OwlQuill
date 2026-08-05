import { useState } from 'react'

type NavigateFn = (s: 'home' | 'character' | 'story' | 'storylab' | 'messaging' | 'notifications' | 'creation') => void

interface HomeFeedProps {
  onNavigate: NavigateFn
}

const POSTS = [
  {
    id: 1,
    character: 'Pan',
    species: 'Human',
    avatar: 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=80&h=80&fit=crop&auto=format',
    type: 'IC',
    realm: 'The Verdant Coast',
    time: '2h ago',
    text: 'A good breakfast is always vital.',
    subtext: 'The tomatoes came in heavy overnight. There is something about the weight of a ripe tomato in your palm — the way it yields just slightly — that tells you the season is turning.',
    image: 'https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=700&h=420&fit=crop&auto=format',
    likes: 47,
    replies: 12,
    shares: 3,
  },
  {
    id: 2,
    character: 'Summer Vael',
    species: 'Elven Wanderer · 1,247 years',
    avatar: 'https://images.unsplash.com/photo-1488716820095-cbe80883c496?w=80&h=80&fit=crop&auto=format',
    type: 'IC',
    realm: 'The Shattered Isles',
    time: '5h ago',
    text: 'The tide does not ask permission to return.',
    subtext: 'I have watched eleven hundred tides. Each one arrives as though it invented itself, certain of its right to shore. There is a lesson in that certainty I have never entirely learned.',
    image: null,
    likes: 134,
    replies: 28,
    shares: 19,
  },
  {
    id: 3,
    character: 'Shadow',
    species: 'Unknown',
    avatar: 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=80&h=80&fit=crop&auto=format',
    type: 'IC',
    realm: 'Midnight Protocol',
    time: '8h ago',
    text: 'Someone moved the mirror again.',
    subtext: 'It does not matter. The reflection was never mine to begin with.',
    image: 'https://images.unsplash.com/photo-1518481612222-68bbe828ecd1?w=700&h=380&fit=crop&auto=format',
    likes: 211,
    replies: 67,
    shares: 44,
  },
  {
    id: 4,
    character: 'Lyra Ashwind',
    species: 'Mage · Scholar of Arcane History',
    avatar: 'https://images.unsplash.com/photo-1531746020798-e6953c6e8e04?w=80&h=80&fit=crop&auto=format',
    type: 'OOC',
    realm: null,
    time: '11h ago',
    text: 'Working on the third chapter of Echoes in the Marbled Dark.',
    subtext: "Lyra's been in the library for three days in-world. I'm deep in research mode myself — turns out historical cartography of fictional coastlines is genuinely absorbing.",
    image: null,
    likes: 89,
    replies: 31,
    shares: 7,
  },
]

const ACTIVE_CHARACTERS = [
  { name: 'Pan', avatar: 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=64&h=64&fit=crop&auto=format', realm: 'The Verdant Coast', dot: true },
  { name: 'Summer Vael', avatar: 'https://images.unsplash.com/photo-1488716820095-cbe80883c496?w=64&h=64&fit=crop&auto=format', realm: 'The Shattered Isles', dot: true },
  { name: 'Shadow', avatar: 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=64&h=64&fit=crop&auto=format', realm: 'Midnight Protocol', dot: false },
  { name: 'Lyra Ashwind', avatar: 'https://images.unsplash.com/photo-1531746020798-e6953c6e8e04?w=64&h=64&fit=crop&auto=format', realm: 'Scholar\'s Quarter', dot: true },
]

const REALMS = [
  { name: 'The Verdant Coast', members: 1_240, genre: 'Contemporary Fantasy', cover: 'https://images.unsplash.com/photo-1499678329028-101435549a4e?w=300&h=120&fit=crop&auto=format' },
  { name: 'Midnight Protocol', members: 876, genre: 'Cyberpunk · Noir', cover: 'https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?w=300&h=120&fit=crop&auto=format' },
]

function PostCard({ post, onNavigate }: { post: typeof POSTS[0]; onNavigate: NavigateFn }) {
  const [liked, setLiked] = useState(false)
  const [bookmarked, setBookmarked] = useState(false)

  return (
    <article style={{
      padding: '28px 0',
      borderBottom: '1px solid var(--border)',
    }}>
      {/* Character attribution */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <button
          onClick={() => post.character === 'Pan' && onNavigate('character')}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
        >
          <div style={{
            width: 38,
            height: 38,
            borderRadius: '50%',
            overflow: 'hidden',
            border: '2px solid var(--border-md)',
            flexShrink: 0,
          }}>
            <img src={post.avatar} alt={post.character} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
          </div>
        </button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <button
              onClick={() => post.character === 'Pan' && onNavigate('character')}
              style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, fontWeight: 600, fontSize: 14, color: 'var(--text)' }}
            >
              {post.character}
            </button>
            <span style={{
              fontSize: 10,
              fontFamily: 'var(--font-mono)',
              fontWeight: 400,
              color: post.type === 'IC' ? 'var(--accent)' : 'var(--text-3)',
              background: post.type === 'IC' ? 'var(--accent-soft)' : 'var(--elevated)',
              border: `1px solid ${post.type === 'IC' ? 'var(--accent-border)' : 'var(--border)'}`,
              borderRadius: 4,
              padding: '2px 6px',
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
            }}>
              {post.type}
            </span>
            {post.realm && (
              <span style={{ fontSize: 12, color: 'var(--text-3)' }}>
                in <span style={{ color: 'var(--text-2)' }}>{post.realm}</span>
              </span>
            )}
          </div>
          <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', marginTop: 1 }}>
            {post.species} · {post.time}
          </div>
        </div>
        <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-3)', padding: 6 }}>
          <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/>
          </svg>
        </button>
      </div>

      {/* Post content */}
      <div style={{ paddingLeft: 0 }}>
        <h3 style={{
          fontFamily: 'var(--font-serif)',
          fontSize: 22,
          fontWeight: 500,
          color: 'var(--text)',
          marginBottom: 8,
          lineHeight: 1.35,
          cursor: post.type === 'IC' ? 'pointer' : 'default',
        }}
          onClick={() => post.type === 'IC' && onNavigate('story')}
        >
          {post.text}
        </h3>
        {post.subtext && (
          <p style={{ fontSize: 14.5, lineHeight: 1.7, color: 'var(--text-2)', marginBottom: post.image ? 16 : 0 }}>
            {post.subtext}
          </p>
        )}
        {post.image && (
          <div style={{
            marginTop: 14,
            borderRadius: 12,
            overflow: 'hidden',
            border: '1px solid var(--border)',
            cursor: 'pointer',
          }}
            onClick={() => onNavigate('story')}
          >
            <img
              src={post.image}
              alt={post.text}
              style={{ width: '100%', height: 'auto', maxHeight: 380, objectFit: 'cover', display: 'block' }}
            />
          </div>
        )}
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 2, marginTop: 16 }}>
        <button
          onClick={() => setLiked(l => !l)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: liked ? 'var(--accent)' : 'var(--text-3)',
            fontSize: 13,
            padding: '6px 10px',
            borderRadius: 8,
            fontWeight: 500,
          }}
        >
          <svg width={15} height={15} viewBox="0 0 24 24" fill={liked ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
          </svg>
          {post.likes + (liked ? 1 : 0)}
        </button>
        <button style={{
          display: 'flex', alignItems: 'center', gap: 6,
          background: 'none', border: 'none', cursor: 'pointer',
          color: 'var(--text-3)', fontSize: 13, padding: '6px 10px', borderRadius: 8, fontWeight: 500,
        }}>
          <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          {post.replies}
        </button>
        <button style={{
          display: 'flex', alignItems: 'center', gap: 6,
          background: 'none', border: 'none', cursor: 'pointer',
          color: 'var(--text-3)', fontSize: 13, padding: '6px 10px', borderRadius: 8, fontWeight: 500,
        }}>
          <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>
          </svg>
          {post.shares}
        </button>
        <div style={{ flex: 1 }} />
        <button
          onClick={() => setBookmarked(b => !b)}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: bookmarked ? 'var(--accent)' : 'var(--text-3)',
            padding: '6px 10px', borderRadius: 8,
          }}
        >
          <svg width={15} height={15} viewBox="0 0 24 24" fill={bookmarked ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
          </svg>
        </button>
      </div>
    </article>
  )
}

export default function HomeFeed({ onNavigate }: HomeFeedProps) {
  const [tab, setTab] = useState<'all' | 'following' | 'realms'>('all')
  const [composing, setComposing] = useState(false)
  const [draft, setDraft] = useState('')
  const [selectedChar, setSelectedChar] = useState('— writing as myself —')

  return (
    <div style={{ display: 'flex', flex: 1, overflow: 'hidden', height: '100%' }}>
      {/* Main feed */}
      <div style={{
        flex: 1,
        overflow: 'hidden auto',
        display: 'flex',
        flexDirection: 'column',
        minWidth: 0,
      }}
        className="hide-scrollbar"
      >
        <div style={{ maxWidth: 640, margin: '0 auto', width: '100%', padding: '40px 32px' }}>
          {/* Header */}
          <div style={{ marginBottom: 32 }}>
            <h1 style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 36,
              fontWeight: 500,
              color: 'var(--text)',
              marginBottom: 20,
              letterSpacing: '-0.02em',
            }}>
              The Commons
            </h1>
            {/* Filter tabs */}
            <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--border)', paddingBottom: 0 }}>
              {(['all', 'following', 'realms'] as const).map(t => (
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
                    padding: '8px 14px',
                    borderBottom: `2px solid ${tab === t ? 'var(--accent)' : 'transparent'}`,
                    textTransform: 'capitalize',
                    letterSpacing: '0.01em',
                    marginBottom: -1,
                    borderRadius: '6px 6px 0 0',
                  }}
                >
                  {t === 'all' ? 'Everything' : t === 'following' ? 'Following' : 'Realms'}
                </button>
              ))}
            </div>
          </div>

          {/* Compose area */}
          <div style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 16,
            padding: composing ? '20px' : '16px 20px',
            marginBottom: 8,
            transition: 'all 200ms ease',
          }}>
            <div style={{ display: 'flex', gap: 12, alignItems: composing ? 'flex-start' : 'center' }}>
              <div style={{ width: 34, height: 34, borderRadius: '50%', overflow: 'hidden', flexShrink: 0 }}>
                <img src="https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=68&h=68&fit=crop&auto=format" alt="You" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                {!composing ? (
                  <button
                    onClick={() => setComposing(true)}
                    style={{
                      background: 'var(--elevated)',
                      border: '1px solid var(--border)',
                      borderRadius: 10,
                      padding: '10px 16px',
                      width: '100%',
                      textAlign: 'left',
                      cursor: 'text',
                      color: 'var(--text-3)',
                      fontSize: 14,
                      fontFamily: 'var(--font-sans)',
                    }}
                  >
                    What's happening in your world?
                  </button>
                ) : (
                  <div>
                    <div style={{ marginBottom: 12 }}>
                      <select
                        value={selectedChar}
                        onChange={e => setSelectedChar(e.target.value)}
                        style={{
                          background: 'var(--elevated)',
                          border: '1px solid var(--border)',
                          borderRadius: 8,
                          padding: '6px 12px',
                          fontSize: 13,
                          color: 'var(--text-2)',
                          cursor: 'pointer',
                        }}
                      >
                        <option>— writing as myself —</option>
                        <option>Pan</option>
                        <option>Lyra Ashwind</option>
                      </select>
                    </div>
                    <textarea
                      autoFocus
                      value={draft}
                      onChange={e => setDraft(e.target.value)}
                      placeholder="Share a moment, a thought, an observation..."
                      style={{
                        width: '100%',
                        minHeight: 100,
                        background: 'transparent',
                        border: 'none',
                        resize: 'none',
                        fontSize: 15,
                        lineHeight: 1.65,
                        color: 'var(--text)',
                        fontFamily: 'var(--font-sans)',
                      }}
                    />
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
                      <button
                        onClick={() => { setComposing(false); setDraft('') }}
                        style={{
                          background: 'none',
                          border: '1px solid var(--border-md)',
                          borderRadius: 8,
                          padding: '7px 16px',
                          cursor: 'pointer',
                          color: 'var(--text-2)',
                          fontSize: 13,
                          fontWeight: 500,
                        }}
                      >
                        Cancel
                      </button>
                      <button style={{
                        background: 'var(--accent)',
                        border: 'none',
                        borderRadius: 8,
                        padding: '7px 20px',
                        cursor: 'pointer',
                        color: '#fff',
                        fontSize: 13,
                        fontWeight: 600,
                        opacity: draft.length > 0 ? 1 : 0.5,
                      }}>
                        Post
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Feed */}
          <div style={{ marginTop: 8 }}>
            {POSTS.map(post => (
              <PostCard key={post.id} post={post} onNavigate={onNavigate} />
            ))}
          </div>
        </div>
      </div>

      {/* Right panel */}
      <div style={{
        width: 300,
        flexShrink: 0,
        borderLeft: '1px solid var(--border)',
        padding: '40px 24px',
        overflow: 'hidden auto',
        display: 'flex',
        flexDirection: 'column',
        gap: 36,
      }}
        className="hide-scrollbar"
      >
        {/* Active characters */}
        <section>
          <h3 style={{
            fontSize: 11,
            fontFamily: 'var(--font-mono)',
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            color: 'var(--text-3)',
            marginBottom: 16,
          }}>
            Active Now
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {ACTIVE_CHARACTERS.map(char => (
              <button
                key={char.name}
                onClick={() => char.name === 'Pan' && onNavigate('character')}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  padding: '6px 8px',
                  borderRadius: 10,
                  textAlign: 'left',
                  width: '100%',
                }}
                className="hover:bg-[var(--elevated)]"
              >
                <div style={{ position: 'relative', flexShrink: 0 }}>
                  <div style={{ width: 36, height: 36, borderRadius: '50%', overflow: 'hidden', border: '1.5px solid var(--border-md)' }}>
                    <img src={char.avatar} alt={char.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  </div>
                  <span style={{
                    position: 'absolute',
                    bottom: 1,
                    right: 1,
                    width: 9,
                    height: 9,
                    borderRadius: '50%',
                    background: char.dot ? '#2ec27e' : 'var(--text-3)',
                    border: '2px solid var(--bg)',
                  }} />
                </div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', lineHeight: 1.3 }}>{char.name}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-3)', lineHeight: 1.3 }}>{char.realm}</div>
                </div>
              </button>
            ))}
          </div>
        </section>

        {/* Featured Realms */}
        <section>
          <h3 style={{
            fontSize: 11,
            fontFamily: 'var(--font-mono)',
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            color: 'var(--text-3)',
            marginBottom: 16,
          }}>
            Featured Realms
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {REALMS.map(realm => (
              <button
                key={realm.name}
                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, textAlign: 'left' }}
              >
                <div style={{
                  borderRadius: 12,
                  overflow: 'hidden',
                  border: '1px solid var(--border)',
                }}>
                  <div style={{ height: 72, overflow: 'hidden', position: 'relative' }}>
                    <img src={realm.cover} alt={realm.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(to top, rgba(8,8,9,0.7), transparent)' }} />
                  </div>
                  <div style={{ padding: '10px 12px', background: 'var(--surface)' }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', lineHeight: 1.3 }}>{realm.name}</div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
                      <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{realm.genre}</span>
                      <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>{realm.members.toLocaleString()}</span>
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>
          <button style={{
            marginTop: 12,
            width: '100%',
            background: 'none',
            border: '1px solid var(--border)',
            borderRadius: 10,
            padding: '9px',
            cursor: 'pointer',
            fontSize: 12,
            fontWeight: 500,
            color: 'var(--text-2)',
          }}>
            Browse all Realms
          </button>
        </section>

        {/* Suggested characters */}
        <section>
          <h3 style={{
            fontSize: 11,
            fontFamily: 'var(--font-mono)',
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            color: 'var(--text-3)',
            marginBottom: 16,
          }}>
            Characters to Follow
          </h3>
          {[
            { name: 'Calyx', note: 'Dragon · The Shattered Isles', avatar: 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=64&h=64&fit=crop&auto=format' },
            { name: 'Mira Solenne', note: 'Historian · Midnight Protocol', avatar: 'https://images.unsplash.com/photo-1438761681033-6461ffad8d80?w=64&h=64&fit=crop&auto=format' },
          ].map(s => (
            <div key={s.name} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
              <div style={{ width: 34, height: 34, borderRadius: '50%', overflow: 'hidden', flexShrink: 0, border: '1.5px solid var(--border-md)' }}>
                <img src={s.avatar} alt={s.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)' }}>{s.name}</div>
                <div style={{ fontSize: 11, color: 'var(--text-3)' }}>{s.note}</div>
              </div>
              <button style={{
                background: 'var(--accent-soft)',
                border: '1px solid var(--accent-border)',
                borderRadius: 8,
                padding: '4px 12px',
                cursor: 'pointer',
                fontSize: 12,
                fontWeight: 600,
                color: 'var(--accent)',
              }}>
                Follow
              </button>
            </div>
          ))}
        </section>
      </div>
    </div>
  )
}
