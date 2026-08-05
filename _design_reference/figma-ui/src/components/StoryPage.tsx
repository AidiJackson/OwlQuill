import { useState } from 'react'

type NavigateFn = (s: 'home' | 'character' | 'story' | 'storylab' | 'messaging' | 'notifications' | 'creation') => void

interface Props { onNavigate: NavigateFn }

export default function StoryPage({ onNavigate }: Props) {
  const [chapter, setChapter] = useState(3)
  const [bookmarked, setBookmarked] = useState(false)
  const [fontSize, setFontSize] = useState(19)

  const totalChapters = 3

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Top bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '14px 32px',
        borderBottom: '1px solid var(--border)',
        flexShrink: 0,
      }}>
        <button
          onClick={() => onNavigate('character')}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-3)', display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}
        >
          <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5M12 5l-7 7 7 7"/></svg>
          Pan
        </button>
        <span style={{ color: 'var(--border-md)', fontSize: 12 }}>/</span>
        <span style={{ fontSize: 13, color: 'var(--text-2)', fontFamily: 'var(--font-serif)' }}>The Weight of Morning Light</span>
        <div style={{ flex: 1 }} />
        {/* Reading controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            onClick={() => setFontSize(f => Math.max(15, f - 1))}
            style={{ background: 'var(--elevated)', border: '1px solid var(--border)', borderRadius: 7, padding: '5px 10px', cursor: 'pointer', color: 'var(--text-2)', fontSize: 12, fontWeight: 600 }}
          >A−</button>
          <button
            onClick={() => setFontSize(f => Math.min(26, f + 1))}
            style={{ background: 'var(--elevated)', border: '1px solid var(--border)', borderRadius: 7, padding: '5px 10px', cursor: 'pointer', color: 'var(--text-2)', fontSize: 14, fontWeight: 600 }}
          >A+</button>
        </div>
        <button
          onClick={() => setBookmarked(b => !b)}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: bookmarked ? 'var(--accent)' : 'var(--text-3)', padding: 6 }}
        >
          <svg width={16} height={16} viewBox="0 0 24 24" fill={bookmarked ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
          </svg>
        </button>
      </div>

      <div style={{ flex: 1, overflow: 'hidden', display: 'flex' }}>
        {/* Chapter sidebar */}
        <div style={{
          width: 220,
          flexShrink: 0,
          borderRight: '1px solid var(--border)',
          padding: '28px 0',
          overflow: 'hidden auto',
        }}
          className="hide-scrollbar"
        >
          <div style={{ padding: '0 20px 16px', fontSize: 11, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--text-3)' }}>
            Chapters
          </div>
          {[
            { n: 1, title: 'Before the Tide Comes In', words: '4,100' },
            { n: 2, title: 'What the Garden Remembers', words: '5,300' },
            { n: 3, title: 'The Garden Before Dawn', words: '4,800' },
          ].map(ch => (
            <button
              key={ch.n}
              onClick={() => setChapter(ch.n)}
              style={{
                display: 'block',
                width: '100%',
                background: chapter === ch.n ? 'var(--accent-soft)' : 'none',
                border: 'none',
                borderLeft: `3px solid ${chapter === ch.n ? 'var(--accent)' : 'transparent'}`,
                padding: '12px 20px 12px 18px',
                cursor: 'pointer',
                textAlign: 'left',
              }}
            >
              <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: chapter === ch.n ? 'var(--accent)' : 'var(--text-3)', marginBottom: 3, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                Chapter {ch.n}
              </div>
              <div style={{ fontSize: 13, fontWeight: 500, color: chapter === ch.n ? 'var(--text)' : 'var(--text-2)', lineHeight: 1.35, marginBottom: 4 }}>
                {ch.title}
              </div>
              <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>{ch.words} words</div>
            </button>
          ))}
        </div>

        {/* Reading area */}
        <div style={{ flex: 1, overflow: 'hidden auto', padding: '56px 0' }} className="hide-scrollbar">
          <div style={{ maxWidth: 660, margin: '0 auto', padding: '0 48px' }}>
            {/* Story header */}
            <div style={{ marginBottom: 56, textAlign: 'center' }}>
              <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 16 }}>
                Chapter {chapter} of {totalChapters}
              </div>
              <h1 style={{
                fontFamily: 'var(--font-serif)',
                fontSize: 'clamp(28px, 4vw, 42px)',
                fontWeight: 500,
                color: 'var(--text)',
                lineHeight: 1.25,
                letterSpacing: '-0.01em',
                marginBottom: 24,
              }}>
                The Garden Before Dawn
              </h1>
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 16 }}>
                <button
                  onClick={() => onNavigate('character')}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'none', border: 'none', cursor: 'pointer' }}
                >
                  <div style={{ width: 28, height: 28, borderRadius: '50%', overflow: 'hidden', border: '1.5px solid var(--border-md)' }}>
                    <img src="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=56&h=56&fit=crop&auto=format" alt="Pan" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  </div>
                  <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-2)' }}>Pan</span>
                </button>
                <span style={{ color: 'var(--text-3)', fontSize: 12 }}>·</span>
                <span style={{ fontSize: 12, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>4,800 words</span>
                <span style={{ color: 'var(--text-3)', fontSize: 12 }}>·</span>
                <span style={{ fontSize: 12, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>~18 min read</span>
              </div>
              <div style={{ margin: '24px auto 0', width: 40, height: 1, background: 'var(--border-md)' }} />
            </div>

            {/* Prose */}
            <div style={{ fontFamily: 'var(--font-serif)', fontSize: fontSize, lineHeight: 1.85, color: 'var(--text)', transition: 'font-size 150ms ease' }}>
              <p style={{ marginBottom: '1.5em' }}>
                He stood in the garden before dawn had properly broken, watching the light change over the sea cliff. It was not yet the hour when colours arrived — everything remained in that early grey that made the rosemary look like smoke and the stone wall like something older than it was.
              </p>
              <p style={{ marginBottom: '1.5em' }}>
                Pan had been awake since three. Not from worry, or not only from worry, but from the particular restlessness that came in the weeks before the autumn shift, when the coastal winds turned and the garden needed different things from him than it had in summer.
              </p>
              <p style={{ marginBottom: '1.5em' }}>
                He knelt beside the tomatoes. The fruit was coming in too fast now — more than he had planted for, more than last year. He did not know whether to be pleased by this or uneasy. Abundance, in his experience, was never entirely simple.
              </p>
              <p style={{ marginBottom: '1.5em', fontStyle: 'italic', color: 'var(--text-2)' }}>
                The first tomato he picked that morning was still warm from the day before.
              </p>
              <p style={{ marginBottom: '1.5em' }}>
                He held it for a moment in both hands. There was something about the weight of it that steadied him — that solid, yielding heaviness. Evidence that something had grown without requiring him to understand how. He found that useful on mornings like this one.
              </p>
              <p style={{ marginBottom: '1.5em' }}>
                By the time the sun had cleared the cliff edge and the light had turned gold enough to cast shadows, he had filled half the basket. The other half he left. The season would not wait for him, but it would not hurry either.
              </p>
              <p style={{ marginBottom: '1.5em' }}>
                He washed his hands at the outdoor tap and stood for a moment with water still running down his forearms, looking at the sea. The tide was going out. It did that without him, too.
              </p>
            </div>

            {/* Chapter navigation */}
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginTop: 72,
              paddingTop: 32,
              borderTop: '1px solid var(--border)',
            }}>
              <button
                onClick={() => setChapter(c => Math.max(1, c - 1))}
                disabled={chapter === 1}
                style={{
                  background: 'var(--elevated)',
                  border: '1px solid var(--border)',
                  borderRadius: 10,
                  padding: '10px 20px',
                  cursor: chapter === 1 ? 'not-allowed' : 'pointer',
                  color: chapter === 1 ? 'var(--text-3)' : 'var(--text-2)',
                  fontSize: 13,
                  fontWeight: 500,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  opacity: chapter === 1 ? 0.4 : 1,
                }}
              >
                <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5M12 5l-7 7 7 7"/></svg>
                Previous
              </button>
              <button
                onClick={() => setChapter(c => Math.min(totalChapters, c + 1))}
                disabled={chapter === totalChapters}
                style={{
                  background: chapter === totalChapters ? 'var(--elevated)' : 'var(--accent)',
                  border: 'none',
                  borderRadius: 10,
                  padding: '10px 20px',
                  cursor: chapter === totalChapters ? 'not-allowed' : 'pointer',
                  color: '#fff',
                  fontSize: 13,
                  fontWeight: 600,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  opacity: chapter === totalChapters ? 0.4 : 1,
                }}
              >
                Next chapter
                <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
