import { useState } from 'react'

type NavigateFn = (s: 'home' | 'character' | 'story' | 'storylab' | 'messaging' | 'notifications' | 'creation') => void

interface Props { onNavigate: NavigateFn }

const CONVERSATIONS = [
  {
    id: 1,
    character: 'Pan',
    avatar: 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=80&h=80&fit=crop&auto=format',
    lastMessage: 'Did you feel that? The tide shifted at dawn.',
    time: '2h',
    unread: 2,
    online: true,
  },
  {
    id: 2,
    character: 'Summer Vael',
    avatar: 'https://images.unsplash.com/photo-1488716820095-cbe80883c496?w=80&h=80&fit=crop&auto=format',
    lastMessage: 'I have been thinking about what you said.',
    time: '5h',
    unread: 0,
    online: true,
  },
  {
    id: 3,
    character: 'Shadow',
    avatar: 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=80&h=80&fit=crop&auto=format',
    lastMessage: 'The mirror is not broken. You are.',
    time: '1d',
    unread: 1,
    online: false,
  },
  {
    id: 4,
    character: 'Lyra Ashwind',
    avatar: 'https://images.unsplash.com/photo-1531746020798-e6953c6e8e04?w=80&h=80&fit=crop&auto=format',
    lastMessage: "Chapter four is finished. You\'ll want to read it.",
    time: '2d',
    unread: 0,
    online: true,
  },
]

const MESSAGES_BY_ID: Record<number, { id: number; from: 'them' | 'me'; text: string; time: string }[]> = {
  1: [
    { id: 1, from: 'them', text: 'The garden was quiet this morning.', time: '09:12' },
    { id: 2, from: 'me', text: "I noticed. The birds were late too.", time: '09:15' },
    { id: 3, from: 'them', text: 'Did you feel that? The tide shifted at dawn. Earlier than usual.', time: '09:18' },
    { id: 4, from: 'me', text: 'Three days early if the almanac is right. Something is moving.', time: '09:22' },
    { id: 5, from: 'them', text: 'Come to the coast this afternoon. I want to show you something in the rock shelf.', time: '09:24' },
  ],
  2: [
    { id: 1, from: 'them', text: 'I have been thinking about what you said. About time and tides.', time: '14:30' },
    { id: 2, from: 'me', text: 'I say many things. Which part stayed with you?', time: '14:45' },
    { id: 3, from: 'them', text: 'The part about patience not being the same as waiting.', time: '14:48' },
  ],
  3: [
    { id: 1, from: 'them', text: 'You moved the mirror.', time: '03:14' },
    { id: 2, from: 'me', text: "I haven\'t touched it.", time: '07:02' },
    { id: 3, from: 'them', text: 'The mirror is not broken. You are.', time: '07:05' },
  ],
  4: [
    { id: 1, from: 'them', text: 'Chapter four is finished. You\'ll want to read it.', time: 'Mon' },
    { id: 2, from: 'me', text: "Sending it now?", time: 'Mon' },
    { id: 3, from: 'them', text: "When the archive stops trying to keep its secrets. Which may be soon.", time: 'Mon' },
  ],
}

export default function Messaging({ onNavigate }: Props) {
  const [activeConv, setActiveConv] = useState(1)
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState(MESSAGES_BY_ID)

  const conv = CONVERSATIONS.find(c => c.id === activeConv)!
  const msgs = messages[activeConv] || []

  const send = () => {
    if (!draft.trim()) return
    setMessages(prev => ({
      ...prev,
      [activeConv]: [...(prev[activeConv] || []), {
        id: Date.now(),
        from: 'me',
        text: draft.trim(),
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }],
    }))
    setDraft('')
  }

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', height: '100%' }}>
      {/* Conversation list */}
      <div style={{
        width: 280,
        flexShrink: 0,
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}>
        <div style={{ padding: '24px 20px 16px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
          <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: 22, fontWeight: 500, color: 'var(--text)', marginBottom: 12 }}>Messages</h2>
          <input
            placeholder="Search conversations..."
            style={{
              width: '100%',
              background: 'var(--elevated)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              padding: '8px 12px',
              fontSize: 13,
              color: 'var(--text)',
            }}
          />
        </div>
        <div style={{ flex: 1, overflow: 'hidden auto' }} className="hide-scrollbar">
          {CONVERSATIONS.map(conv => (
            <button
              key={conv.id}
              onClick={() => setActiveConv(conv.id)}
              style={{
                display: 'flex',
                gap: 12,
                width: '100%',
                background: activeConv === conv.id ? 'var(--accent-soft)' : 'transparent',
                border: 'none',
                borderLeft: `3px solid ${activeConv === conv.id ? 'var(--accent)' : 'transparent'}`,
                padding: '14px 16px 14px 14px',
                cursor: 'pointer',
                textAlign: 'left',
                alignItems: 'flex-start',
              }}
            >
              <div style={{ position: 'relative', flexShrink: 0 }}>
                <div style={{ width: 40, height: 40, borderRadius: '50%', overflow: 'hidden', border: '1.5px solid var(--border-md)' }}>
                  <img src={conv.avatar} alt={conv.character} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                </div>
                {conv.online && (
                  <span style={{
                    position: 'absolute',
                    bottom: 1,
                    right: 1,
                    width: 9,
                    height: 9,
                    borderRadius: '50%',
                    background: '#2ec27e',
                    border: '2px solid var(--surface)',
                  }} />
                )}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 3 }}>
                  <span style={{ fontSize: 13.5, fontWeight: activeConv === conv.id || conv.unread > 0 ? 600 : 500, color: 'var(--text)' }}>
                    {conv.character}
                  </span>
                  <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', flexShrink: 0, marginLeft: 8 }}>{conv.time}</span>
                </div>
                <div style={{
                  fontSize: 12.5,
                  color: conv.unread > 0 ? 'var(--text-2)' : 'var(--text-3)',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  fontStyle: 'italic',
                  lineHeight: 1.4,
                }}>
                  "{conv.lastMessage}"
                </div>
              </div>
              {conv.unread > 0 && (
                <div style={{
                  width: 18,
                  height: 18,
                  borderRadius: '50%',
                  background: 'var(--accent)',
                  color: '#fff',
                  fontSize: 10,
                  fontWeight: 700,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                  fontFamily: 'var(--font-mono)',
                }}>
                  {conv.unread}
                </div>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Thread view */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {/* Thread header */}
        <div style={{
          padding: '16px 24px',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          flexShrink: 0,
        }}>
          <div style={{ position: 'relative' }}>
            <div style={{ width: 38, height: 38, borderRadius: '50%', overflow: 'hidden', border: '2px solid var(--border-md)' }}>
              <img src={conv.avatar} alt={conv.character} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
            </div>
            {conv.online && (
              <span style={{
                position: 'absolute',
                bottom: 1,
                right: 1,
                width: 9,
                height: 9,
                borderRadius: '50%',
                background: '#2ec27e',
                border: '2px solid var(--bg)',
              }} />
            )}
          </div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{conv.character}</div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
              {conv.online ? 'Active now' : 'Last seen 1 day ago'}
            </div>
          </div>
          <div style={{ flex: 1 }} />
          <button
            onClick={() => onNavigate('character')}
            style={{ background: 'var(--elevated)', border: '1px solid var(--border)', borderRadius: 8, padding: '7px 14px', cursor: 'pointer', fontSize: 12, color: 'var(--text-2)', fontWeight: 500 }}
          >
            View Character
          </button>
        </div>

        {/* Messages */}
        <div style={{ flex: 1, overflow: 'hidden auto', padding: '24px 32px', display: 'flex', flexDirection: 'column', gap: 12 }} className="hide-scrollbar">
          {msgs.map(msg => (
            <div key={msg.id} style={{
              display: 'flex',
              justifyContent: msg.from === 'me' ? 'flex-end' : 'flex-start',
              alignItems: 'flex-end',
              gap: 8,
            }}>
              {msg.from === 'them' && (
                <div style={{ width: 28, height: 28, borderRadius: '50%', overflow: 'hidden', flexShrink: 0 }}>
                  <img src={conv.avatar} alt={conv.character} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                </div>
              )}
              <div style={{
                maxWidth: '68%',
                padding: '10px 16px',
                borderRadius: msg.from === 'me' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                background: msg.from === 'me' ? 'var(--accent)' : 'var(--elevated)',
                color: msg.from === 'me' ? '#fff' : 'var(--text)',
                fontSize: 14,
                lineHeight: 1.6,
                fontStyle: 'italic',
              }}>
                "{msg.text}"
              </div>
              <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', flexShrink: 0 }}>{msg.time}</div>
            </div>
          ))}
        </div>

        {/* Input */}
        <div style={{ padding: '16px 24px', borderTop: '1px solid var(--border)', flexShrink: 0 }}>
          <div style={{
            display: 'flex',
            gap: 10,
            alignItems: 'flex-end',
            background: 'var(--elevated)',
            border: '1px solid var(--border-md)',
            borderRadius: 14,
            padding: '10px 14px',
          }}>
            <textarea
              value={draft}
              onChange={e => setDraft(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }}}
              placeholder="Write in character..."
              rows={1}
              style={{
                flex: 1,
                background: 'transparent',
                border: 'none',
                resize: 'none',
                fontSize: 14,
                lineHeight: 1.5,
                color: 'var(--text)',
                fontStyle: 'italic',
                maxHeight: 120,
                overflow: 'hidden auto',
              }}
            />
            <button
              onClick={send}
              style={{
                background: draft.trim() ? 'var(--accent)' : 'transparent',
                border: draft.trim() ? 'none' : '1px solid var(--border)',
                borderRadius: 8,
                padding: '7px 12px',
                cursor: 'pointer',
                color: draft.trim() ? '#fff' : 'var(--text-3)',
                flexShrink: 0,
                transition: 'all 150ms ease',
              }}
            >
              <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            </button>
          </div>
          <div style={{ textAlign: 'center', marginTop: 8 }}>
            <span style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
              Writing as Grace Fielding · Enter to send
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
