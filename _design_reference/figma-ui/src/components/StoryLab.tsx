import { useState } from 'react'

type NavigateFn = (s: 'home' | 'character' | 'story' | 'storylab' | 'messaging' | 'notifications' | 'creation') => void

interface Props { onNavigate?: NavigateFn } // eslint-disable-line @typescript-eslint/no-unused-vars

const CHAPTERS = [
  { id: 1, title: 'Prologue: The Locked Room', words: 420, status: 'done' },
  { id: 2, title: 'Part I — The Scholar Arrives', words: 3240, status: 'done' },
  { id: 3, title: 'The First Inscription', words: 2810, status: 'done' },
  { id: 4, title: 'Night in the Archive', words: 1980, status: 'in-progress' },
  { id: 5, title: 'Part II — The Mirror Gallery', words: 0, status: 'outline' },
  { id: 6, title: 'What the Marble Remembers', words: 0, status: 'outline' },
  { id: 7, title: 'The Price of Translation', words: 0, status: 'outline' },
]

const DRAFT_CONTENT = `She had been in the archive for eleven hours before she found the inscription that should not have existed.

It was not remarkable in itself — a single line of text carved into the inner face of a shelf bracket, where no one would look unless they were searching for something else entirely. Which was how Lyra had come to find it: she had been looking for a loose manuscript page, one corner of which had slipped beneath the bracket in the late afternoon, and in reaching for it her fingers had traced what felt, unmistakably, like language.

She pulled the lamp closer. The oil was nearly gone — she had been rationing it since eight, when she realised she would not be leaving before dark — and the flame was too small for good reading. She held the bracket at an angle and waited for her eyes to adjust.

The text was in the Old Meridian hand, the pre-reform script that had not been in common use for four hundred years. Lyra could read it, of course; that was more or less the entirety of her professional value. What troubled her was not the script.

What troubled her was the date.

The inscription was dated seventeen years before the archive had been built.`

export default function StoryLab({ onNavigate: _onNavigate }: Props) {
  const [activeChapter, setActiveChapter] = useState(4)
  const [content, setContent] = useState(DRAFT_CONTENT)
  const [showAI, setShowAI] = useState(false)
  const [aiQuery, setAiQuery] = useState('')
  const [aiResponse, setAiResponse] = useState('')
  const [focusMode, setFocusMode] = useState(false)
  const [saved, setSaved] = useState(true)

  const wordCount = content.trim().split(/\s+/).filter(Boolean).length
  const totalWords = CHAPTERS.reduce((s, c) => s + c.words, 0) + wordCount

  const handleChange = (v: string) => {
    setContent(v)
    setSaved(false)
    clearTimeout((window as any).__saveTimer)
    ;(window as any).__saveTimer = setTimeout(() => setSaved(true), 1200)
  }

  const handleAiAsk = () => {
    if (!aiQuery.trim()) return
    setAiResponse('')
    const responses: Record<string, string> = {
      default: "The inscription predates the archive by seventeen years — this could suggest either an error in the dating system of the time, or that the archive was built around an older structure, one that has since been deliberately obscured. The marble itself might hold the answer: pre-reform masons often encoded the true construction date in the stone's grain direction.",
    }
    const response = responses.default
    let i = 0
    const timer = setInterval(() => {
      setAiResponse(response.slice(0, i))
      i += 3
      if (i > response.length) clearInterval(timer)
    }, 20)
    setAiQuery('')
  }

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Top bar */}
      {!focusMode && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '12px 20px',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
          background: 'var(--surface)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1 }}>
            <div style={{ width: 28, height: 28, borderRadius: 8, overflow: 'hidden', border: '1.5px solid var(--border-md)' }}>
              <img src="https://images.unsplash.com/photo-1531746020798-e6953c6e8e04?w=56&h=56&fit=crop&auto=format" alt="Lyra" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', fontFamily: 'var(--font-serif)' }}>Echoes in the Marbled Dark</div>
              <div style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>by Lyra Ashwind</div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <span style={{
              fontSize: 11,
              fontFamily: 'var(--font-mono)',
              color: saved ? 'var(--text-3)' : 'var(--accent)',
              display: 'flex',
              alignItems: 'center',
              gap: 5,
            }}>
              {saved ? (
                <><svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5"/></svg>Saved</>
              ) : 'Saving…'}
            </span>
            <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
              {wordCount.toLocaleString()} words this chapter
            </span>
            <button
              onClick={() => setFocusMode(true)}
              style={{ background: 'var(--elevated)', border: '1px solid var(--border)', borderRadius: 8, padding: '6px 12px', cursor: 'pointer', fontSize: 12, color: 'var(--text-2)', fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6 }}
            >
              <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M16 21h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
              Focus
            </button>
            <button
              onClick={() => setShowAI(s => !s)}
              style={{
                background: showAI ? 'var(--accent-soft)' : 'var(--elevated)',
                border: `1px solid ${showAI ? 'var(--accent-border)' : 'var(--border)'}`,
                borderRadius: 8,
                padding: '6px 12px',
                cursor: 'pointer',
                fontSize: 12,
                color: showAI ? 'var(--accent)' : 'var(--text-2)',
                fontWeight: 500,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a7 7 0 0 1 7 7c0 2.9-1.8 5.4-4.4 6.5L14 18H10l-.6-2.5C6.8 14.4 5 11.9 5 9a7 7 0 0 1 7-7z"/><path d="M10 22h4"/></svg>
              AI Studio
            </button>
            <button style={{ background: 'var(--accent)', border: 'none', borderRadius: 8, padding: '6px 16px', cursor: 'pointer', fontSize: 13, fontWeight: 600, color: '#fff' }}>
              Publish
            </button>
          </div>
        </div>
      )}

      <div style={{ flex: 1, overflow: 'hidden', display: 'flex' }}>
        {/* Chapter tree */}
        {!focusMode && (
          <div style={{
            width: 240,
            flexShrink: 0,
            borderRight: '1px solid var(--border)',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}>
            <div style={{ padding: '16px 16px 8px', fontSize: 11, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--text-3)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>Structure</span>
              <span style={{ color: 'var(--accent)', fontWeight: 500 }}>{(totalWords / 1000).toFixed(1)}k</span>
            </div>
            <div style={{ flex: 1, overflow: 'hidden auto' }} className="hide-scrollbar">
              {CHAPTERS.map(ch => (
                <button
                  key={ch.id}
                  onClick={() => setActiveChapter(ch.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    width: '100%',
                    background: activeChapter === ch.id ? 'var(--accent-soft)' : 'none',
                    border: 'none',
                    borderLeft: `3px solid ${activeChapter === ch.id ? 'var(--accent)' : 'transparent'}`,
                    padding: '10px 16px 10px 14px',
                    cursor: 'pointer',
                    textAlign: 'left',
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 500, color: activeChapter === ch.id ? 'var(--text)' : 'var(--text-2)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', lineHeight: 1.4 }}>
                      {ch.title}
                    </div>
                    {ch.words > 0 && (
                      <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', marginTop: 2 }}>
                        {ch.words.toLocaleString()} words
                      </div>
                    )}
                  </div>
                  <div style={{
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    flexShrink: 0,
                    background: ch.status === 'done' ? '#2dc896' : ch.status === 'in-progress' ? 'var(--accent)' : 'var(--text-3)',
                    opacity: ch.status === 'outline' ? 0.4 : 1,
                  }} />
                </button>
              ))}
              <button style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                width: '100%',
                background: 'none',
                border: 'none',
                borderLeft: '3px solid transparent',
                padding: '10px 16px 10px 14px',
                cursor: 'pointer',
                color: 'var(--text-3)',
                fontSize: 12,
              }}>
                <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                Add chapter
              </button>
            </div>

            {/* Stats */}
            <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>Total words</span>
                <span style={{ fontSize: 11, color: 'var(--text-2)', fontFamily: 'var(--font-mono)', fontWeight: 500 }}>{totalWords.toLocaleString()}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>Progress</span>
                <span style={{ fontSize: 11, color: 'var(--text-2)', fontFamily: 'var(--font-mono)', fontWeight: 500 }}>4 / 7 ch</span>
              </div>
              <div style={{ marginTop: 10, height: 3, borderRadius: 3, background: 'var(--elevated)', overflow: 'hidden' }}>
                <div style={{ height: '100%', width: '57%', background: 'var(--accent)', borderRadius: 3 }} />
              </div>
            </div>
          </div>
        )}

        {/* Editor */}
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', position: 'relative' }}>
          {focusMode && (
            <button
              onClick={() => setFocusMode(false)}
              style={{
                position: 'absolute',
                top: 20,
                right: 24,
                background: 'rgba(0,0,0,0.3)',
                backdropFilter: 'blur(8px)',
                border: '1px solid var(--border-md)',
                borderRadius: 8,
                padding: '6px 14px',
                cursor: 'pointer',
                color: 'var(--text-2)',
                fontSize: 12,
                fontWeight: 500,
                zIndex: 10,
              }}
            >Exit Focus</button>
          )}
          <div style={{ flex: 1, overflow: 'hidden auto', padding: focusMode ? '80px 0' : '48px 0' }} className="hide-scrollbar">
            <div style={{ maxWidth: 680, margin: '0 auto', padding: '0 48px' }}>
              {!focusMode && (
                <div style={{ marginBottom: 32 }}>
                  <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--text-3)', marginBottom: 8 }}>
                    Chapter {activeChapter}
                  </div>
                  <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: 28, fontWeight: 500, color: 'var(--text)', lineHeight: 1.3 }}>
                    {CHAPTERS.find(c => c.id === activeChapter)?.title}
                  </h2>
                </div>
              )}
              <textarea
                value={content}
                onChange={e => handleChange(e.target.value)}
                style={{
                  width: '100%',
                  minHeight: '60vh',
                  background: 'transparent',
                  border: 'none',
                  resize: 'none',
                  fontFamily: 'var(--font-serif)',
                  fontSize: 19,
                  lineHeight: 1.85,
                  color: 'var(--text)',
                  caretColor: 'var(--accent)',
                  outline: 'none',
                }}
                placeholder="Begin writing..."
                spellCheck
              />
            </div>
          </div>
          {/* Bottom word count */}
          <div style={{
            padding: '10px 48px',
            borderTop: '1px solid var(--border)',
            display: 'flex',
            justifyContent: 'center',
            flexShrink: 0,
          }}>
            <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
              {wordCount.toLocaleString()} words · {Math.ceil(wordCount / 200)} min read
            </span>
          </div>
        </div>

        {/* AI Studio panel */}
        {showAI && !focusMode && (
          <div style={{
            width: 300,
            flexShrink: 0,
            borderLeft: '1px solid var(--border)',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ width: 20, height: 20, borderRadius: '50%', background: 'var(--accent-soft)', border: '1px solid var(--accent-border)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <svg width={11} height={11} viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a7 7 0 0 1 7 7c0 2.9-1.8 5.4-4.4 6.5L14 18H10l-.6-2.5C6.8 14.4 5 11.9 5 9a7 7 0 0 1 7-7z"/></svg>
              </div>
              <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>AI Studio</span>
              <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--accent)', background: 'var(--accent-soft)', borderRadius: 4, padding: '2px 6px', marginLeft: 2 }}>BETA</span>
            </div>

            <div style={{ flex: 1, overflow: 'hidden auto', padding: '20px' }} className="hide-scrollbar">
              {/* Quick actions */}
              <div style={{ marginBottom: 20 }}>
                <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-3)', marginBottom: 10 }}>Quick Actions</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {['Continue from where I left off', 'Suggest next scene', 'Check character consistency', 'Lore check for this chapter'].map(action => (
                    <button
                      key={action}
                      onClick={() => { setAiQuery(action); }}
                      style={{
                        background: 'var(--elevated)',
                        border: '1px solid var(--border)',
                        borderRadius: 8,
                        padding: '9px 12px',
                        cursor: 'pointer',
                        textAlign: 'left',
                        fontSize: 12.5,
                        color: 'var(--text-2)',
                        lineHeight: 1.4,
                      }}
                    >
                      {action}
                    </button>
                  ))}
                </div>
              </div>

              {/* Character reference */}
              <div style={{ marginBottom: 20 }}>
                <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-3)', marginBottom: 10 }}>POV Character</div>
                <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '10px', background: 'var(--elevated)', border: '1px solid var(--border)', borderRadius: 10 }}>
                  <div style={{ width: 32, height: 32, borderRadius: '50%', overflow: 'hidden', border: '1.5px solid var(--border-md)' }}>
                    <img src="https://images.unsplash.com/photo-1531746020798-e6953c6e8e04?w=64&h=64&fit=crop&auto=format" alt="Lyra" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  </div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>Lyra Ashwind</div>
                    <div style={{ fontSize: 11, color: 'var(--text-3)' }}>Mage · Scholar</div>
                  </div>
                </div>
              </div>

              {/* AI response */}
              {aiResponse && (
                <div style={{
                  padding: 14,
                  background: 'var(--accent-soft)',
                  border: '1px solid var(--accent-border)',
                  borderRadius: 10,
                  marginBottom: 16,
                }}>
                  <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--accent)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Response</div>
                  <p style={{ fontSize: 13, lineHeight: 1.65, color: 'var(--text-2)' }}>{aiResponse}</p>
                </div>
              )}
            </div>

            {/* AI input */}
            <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border)', flexShrink: 0 }}>
              <div style={{ display: 'flex', gap: 8 }}>
                <input
                  value={aiQuery}
                  onChange={e => setAiQuery(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleAiAsk()}
                  placeholder="Ask about your story..."
                  style={{
                    flex: 1,
                    background: 'var(--elevated)',
                    border: '1px solid var(--border-md)',
                    borderRadius: 8,
                    padding: '8px 12px',
                    fontSize: 13,
                    color: 'var(--text)',
                  }}
                />
                <button
                  onClick={handleAiAsk}
                  style={{ background: 'var(--accent)', border: 'none', borderRadius: 8, padding: '8px 14px', cursor: 'pointer', color: '#fff' }}
                >
                  <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
