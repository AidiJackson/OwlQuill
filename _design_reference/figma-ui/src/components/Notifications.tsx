import React, { useState } from 'react'

type NavigateFn = (s: 'home' | 'character' | 'story' | 'storylab' | 'messaging' | 'notifications' | 'creation') => void

interface Props { onNavigate: NavigateFn }

const GROUPS = [
  {
    label: 'Today',
    items: [
      {
        id: 1,
        type: 'follow',
        avatar: 'https://images.unsplash.com/photo-1488716820095-cbe80883c496?w=80&h=80&fit=crop&auto=format',
        text: 'Summer Vael followed your character',
        target: 'Lyra Ashwind',
        time: '2 hours ago',
        read: false,
        icon: 'follow',
      },
      {
        id: 2,
        type: 'like',
        avatar: 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=80&h=80&fit=crop&auto=format',
        text: 'Pan liked your post',
        target: '"The archive speaks in angles, not in words."',
        time: '3 hours ago',
        read: false,
        icon: 'like',
      },
      {
        id: 3,
        type: 'reply',
        avatar: 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=80&h=80&fit=crop&auto=format',
        text: 'Shadow replied to your post',
        target: '"Then the words are the lie."',
        time: '4 hours ago',
        read: false,
        icon: 'reply',
      },
      {
        id: 4,
        type: 'story',
        avatar: 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=80&h=80&fit=crop&auto=format',
        text: 'Pan published a new chapter',
        target: 'The Weight of Morning Light — Chapter 3',
        time: '5 hours ago',
        read: true,
        icon: 'story',
      },
    ],
  },
  {
    label: 'Yesterday',
    items: [
      {
        id: 5,
        type: 'mention',
        avatar: 'https://images.unsplash.com/photo-1531746020798-e6953c6e8e04?w=80&h=80&fit=crop&auto=format',
        text: 'Lyra Ashwind mentioned you in',
        target: 'The Verdant Coast realm',
        time: '1 day ago',
        read: true,
        icon: 'mention',
      },
      {
        id: 6,
        type: 'follow',
        avatar: 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=80&h=80&fit=crop&auto=format',
        text: 'Calyx started following your character',
        target: 'Pan',
        time: '1 day ago',
        read: true,
        icon: 'follow',
      },
    ],
  },
  {
    label: 'This week',
    items: [
      {
        id: 7,
        type: 'realm',
        avatar: null,
        text: 'New activity in',
        target: 'The Shattered Isles — 14 new posts',
        time: '3 days ago',
        read: true,
        icon: 'realm',
      },
      {
        id: 8,
        type: 'story',
        avatar: 'https://images.unsplash.com/photo-1438761681033-6461ffad8d80?w=80&h=80&fit=crop&auto=format',
        text: 'Mira Solenne started a new story you might enjoy',
        target: '"The Cartography of Forgetting"',
        time: '4 days ago',
        read: true,
        icon: 'story',
      },
    ],
  },
]

function IconForType({ type }: { type: string }) {
  const s = 12
  const icons: Record<string, React.ReactElement> = {
    follow: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>,
    like: <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>,
    reply: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>,
    story: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>,
    mention: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.92 7.94"/></svg>,
    realm: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>,
  }
  return icons[type] || icons.story
}

export default function Notifications({ onNavigate }: Props) {
  const [filter, setFilter] = useState<'all' | 'unread'>('all')
  const [readIds, setReadIds] = useState<Set<number>>(new Set())

  const markAllRead = () => {
    const all = GROUPS.flatMap(g => g.items.map(i => i.id))
    setReadIds(new Set(all))
  }

  const isRead = (id: number, defaultRead: boolean) => defaultRead || readIds.has(id)

  const filtered = GROUPS.map(g => ({
    ...g,
    items: g.items.filter(i => filter === 'all' || !isRead(i.id, i.read)),
  })).filter(g => g.items.length > 0)

  const unreadCount = GROUPS.flatMap(g => g.items).filter(i => !isRead(i.id, i.read)).length

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Header */}
      <div style={{ padding: '32px 40px 0', flexShrink: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 24 }}>
          <div>
            <h1 style={{ fontFamily: 'var(--font-serif)', fontSize: 32, fontWeight: 500, color: 'var(--text)', marginBottom: 4 }}>Notifications</h1>
            {unreadCount > 0 && (
              <span style={{ fontSize: 13, color: 'var(--text-2)' }}>
                <span style={{ color: 'var(--accent)', fontWeight: 600 }}>{unreadCount}</span> unread
              </span>
            )}
          </div>
          <button
            onClick={markAllRead}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 13, color: 'var(--accent)', fontWeight: 500 }}
          >
            Mark all read
          </button>
        </div>
        {/* Filter */}
        <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--border)' }}>
          {(['all', 'unread'] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                fontSize: 13,
                fontWeight: 500,
                color: filter === f ? 'var(--text)' : 'var(--text-3)',
                padding: '8px 16px',
                borderBottom: `2px solid ${filter === f ? 'var(--accent)' : 'transparent'}`,
                textTransform: 'capitalize',
                marginBottom: -1,
              }}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Notification list */}
      <div style={{ flex: 1, overflow: 'hidden auto', padding: '8px 40px 40px' }} className="hide-scrollbar">
        {filtered.length === 0 && (
          <div style={{ paddingTop: 80, textAlign: 'center' }}>
            <div style={{ fontSize: 14, color: 'var(--text-3)' }}>No unread notifications.</div>
          </div>
        )}
        {filtered.map(group => (
          <div key={group.label}>
            <div style={{
              fontSize: 11,
              fontFamily: 'var(--font-mono)',
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
              color: 'var(--text-3)',
              padding: '24px 0 8px',
            }}>
              {group.label}
            </div>
            {group.items.map(item => {
              const read = isRead(item.id, item.read)
              return (
                <button
                  key={item.id}
                  onClick={() => {
                    setReadIds(prev => new Set([...prev, item.id]))
                    if (item.type === 'story') onNavigate('story')
                    else if (item.type === 'follow' || item.type === 'like' || item.type === 'reply') onNavigate('character')
                  }}
                  style={{
                    display: 'flex',
                    gap: 14,
                    width: '100%',
                    background: read ? 'transparent' : 'var(--accent-soft)',
                    border: 'none',
                    borderBottom: '1px solid var(--border)',
                    padding: '16px 12px',
                    cursor: 'pointer',
                    textAlign: 'left',
                    alignItems: 'flex-start',
                    borderRadius: read ? 0 : 10,
                    marginBottom: read ? 0 : 4,
                    transition: 'background 150ms ease',
                  }}
                >
                  {/* Avatar / icon */}
                  <div style={{ position: 'relative', flexShrink: 0 }}>
                    {item.avatar ? (
                      <div style={{ width: 40, height: 40, borderRadius: '50%', overflow: 'hidden', border: '1.5px solid var(--border-md)' }}>
                        <img src={item.avatar} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                      </div>
                    ) : (
                      <div style={{ width: 40, height: 40, borderRadius: '50%', background: 'var(--elevated)', border: '1.5px solid var(--border-md)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-3)' }}>
                        <IconForType type={item.type} />
                      </div>
                    )}
                    <div style={{
                      position: 'absolute',
                      bottom: -2,
                      right: -2,
                      width: 18,
                      height: 18,
                      borderRadius: '50%',
                      background: 'var(--accent)',
                      border: '2px solid var(--bg)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: '#fff',
                    }}>
                      <IconForType type={item.type} />
                    </div>
                  </div>

                  {/* Content */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14, lineHeight: 1.5, color: read ? 'var(--text-2)' : 'var(--text)', marginBottom: 2 }}>
                      <span style={{ fontWeight: read ? 400 : 600 }}>{item.text}</span>
                    </div>
                    <div style={{ fontSize: 13, color: 'var(--accent)', fontStyle: 'italic', marginBottom: 4, lineHeight: 1.4 }}>
                      {item.target}
                    </div>
                    <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
                      {item.time}
                    </div>
                  </div>

                  {/* Unread dot */}
                  {!read && (
                    <div style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: 'var(--accent)',
                      flexShrink: 0,
                      marginTop: 6,
                    }} />
                  )}
                </button>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
