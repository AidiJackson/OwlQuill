import { useState } from 'react'

type NavigateFn = (s: 'home' | 'character' | 'story' | 'storylab' | 'messaging' | 'notifications' | 'creation') => void

interface Props { onNavigate: NavigateFn }

const STEPS = [
  { id: 'identity',    label: 'Identity',    description: 'Name, species, and public presence' },
  { id: 'appearance',  label: 'Appearance',  description: 'How they look to the world' },
  { id: 'backstory',   label: 'Backstory',   description: 'Who they were before now' },
  { id: 'voice',       label: 'Voice',       description: 'How they speak and think' },
  { id: 'world',       label: 'World',       description: 'Where they belong' },
]

const SPECIES_OPTIONS = ['Human', 'Elf', 'Dragon (shifted)', 'Fae', 'Undead', 'Construct', 'Unknown', 'Other…']
const REALM_OPTIONS = ['The Verdant Coast', 'Midnight Protocol', 'The Shattered Isles', "Scholar's Quarter", 'The Unmarked Roads', 'Create new realm…']

export default function CharacterCreation({ onNavigate }: Props) {
  const [step, setStep] = useState(0)
  const [form, setForm] = useState({
    name: '',
    species: '',
    tagline: '',
    visibility: 'public' as 'public' | 'private' | 'friends',
    identityLocked: false,
    portraitUrl: '',
    coverUrl: '',
    age: '',
    physicalNotes: '',
    backstory: '',
    voice: '',
    quirks: '',
    realm: '',
    loreNotes: '',
  })

  const update = (key: keyof typeof form, value: string | boolean) =>
    setForm(prev => ({ ...prev, [key]: value }))

  const currentStep = STEPS[step]
  const progress = ((step) / STEPS.length) * 100

  const handleSubmit = () => {
    onNavigate('character')
  }

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', height: '100%' }}>
      {/* Left panel — steps */}
      <div style={{
        width: 280,
        flexShrink: 0,
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        padding: '40px 24px',
        overflow: 'hidden auto',
      }}
        className="hide-scrollbar"
      >
        <div style={{ marginBottom: 36 }}>
          <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--text-3)', marginBottom: 8 }}>
            New Character
          </div>
          <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: 24, fontWeight: 500, color: 'var(--text)', lineHeight: 1.3 }}>
            {form.name || 'Untitled'}
          </h2>
          {form.species && (
            <div style={{ fontSize: 13, color: 'var(--text-3)', marginTop: 4 }}>{form.species}</div>
          )}
        </div>

        {/* Progress */}
        <div style={{ marginBottom: 32 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>Progress</span>
            <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-2)' }}>{step + 1} / {STEPS.length}</span>
          </div>
          <div style={{ height: 3, background: 'var(--elevated)', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${progress}%`, background: 'var(--accent)', borderRadius: 3, transition: 'width 300ms ease' }} />
          </div>
        </div>

        {/* Steps list */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {STEPS.map((s, i) => (
            <button
              key={s.id}
              onClick={() => i <= step && setStep(i)}
              style={{
                display: 'flex',
                gap: 12,
                alignItems: 'flex-start',
                padding: '12px 14px',
                borderRadius: 10,
                background: i === step ? 'var(--accent-soft)' : 'transparent',
                border: 'none',
                cursor: i <= step ? 'pointer' : 'default',
                textAlign: 'left',
                opacity: i > step ? 0.45 : 1,
              }}
            >
              <div style={{
                width: 22,
                height: 22,
                borderRadius: '50%',
                background: i < step ? 'var(--accent)' : i === step ? 'var(--accent-soft)' : 'var(--elevated)',
                border: `1.5px solid ${i <= step ? 'var(--accent-border)' : 'var(--border)'}`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                marginTop: 1,
              }}>
                {i < step ? (
                  <svg width={11} height={11} viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
                ) : (
                  <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: i === step ? 'var(--accent)' : 'var(--text-3)', fontWeight: 600 }}>{i + 1}</span>
                )}
              </div>
              <div>
                <div style={{ fontSize: 13, fontWeight: i === step ? 600 : 500, color: i === step ? 'var(--text)' : 'var(--text-2)' }}>{s.label}</div>
                <div style={{ fontSize: 11, color: 'var(--text-3)', lineHeight: 1.4, marginTop: 2 }}>{s.description}</div>
              </div>
            </button>
          ))}
        </div>

        {/* Preview card */}
        {(form.name || form.portraitUrl) && (
          <div style={{ marginTop: 'auto', paddingTop: 32 }}>
            <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-3)', marginBottom: 10 }}>Preview</div>
            <div style={{ border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden', background: 'var(--surface)' }}>
              <div style={{ height: 60, background: form.coverUrl ? `url(${form.coverUrl}) center/cover` : 'linear-gradient(135deg, var(--elevated), var(--overlay))' }} />
              <div style={{ padding: '8px 12px 12px' }}>
                <div style={{ width: 32, height: 32, borderRadius: '50%', border: '2px solid var(--bg)', marginTop: -16, overflow: 'hidden', background: 'var(--elevated)' }}>
                  {form.portraitUrl && <img src={form.portraitUrl} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />}
                </div>
                <div style={{ fontFamily: 'var(--font-serif)', fontSize: 15, fontWeight: 500, color: 'var(--text)', marginTop: 6 }}>{form.name || '—'}</div>
                {form.species && <div style={{ fontSize: 11, color: 'var(--text-3)' }}>{form.species}</div>}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Right panel — form */}
      <div style={{ flex: 1, overflow: 'hidden auto', padding: '48px' }} className="hide-scrollbar">
        <div style={{ maxWidth: 560 }}>
          <div style={{ marginBottom: 36 }}>
            <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.12em', color: 'var(--accent)', marginBottom: 8 }}>
              Step {step + 1} — {currentStep.label}
            </div>
            <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: 28, fontWeight: 500, color: 'var(--text)', lineHeight: 1.3 }}>
              {step === 0 && 'Who are they?'}
              {step === 1 && 'How do they appear?'}
              {step === 2 && 'What shaped them?'}
              {step === 3 && 'How do they speak?'}
              {step === 4 && 'Where do they belong?'}
            </h3>
          </div>

          {/* Step 0: Identity */}
          {step === 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
              <Field label="Character name" required>
                <input
                  value={form.name}
                  onChange={e => update('name', e.target.value)}
                  placeholder="e.g. Lyra, Pan, Shadow…"
                  style={inputStyle}
                  autoFocus
                />
              </Field>
              <Field label="Species or nature" hint="How they exist in the world">
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
                  {SPECIES_OPTIONS.map(s => (
                    <button
                      key={s}
                      onClick={() => update('species', s)}
                      style={{
                        background: form.species === s ? 'var(--accent)' : 'var(--elevated)',
                        border: `1px solid ${form.species === s ? 'var(--accent)' : 'var(--border-md)'}`,
                        borderRadius: 8,
                        padding: '7px 14px',
                        cursor: 'pointer',
                        fontSize: 13,
                        color: form.species === s ? '#fff' : 'var(--text-2)',
                        fontWeight: form.species === s ? 600 : 400,
                        transition: 'all 150ms ease',
                      }}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </Field>
              <Field label="Tagline" hint="One sentence about who they are">
                <input
                  value={form.tagline}
                  onChange={e => update('tagline', e.target.value)}
                  placeholder="A man who tends his garden as carefully as his words."
                  style={inputStyle}
                />
              </Field>
              <Field label="Visibility">
                <div style={{ display: 'flex', gap: 8 }}>
                  {(['public', 'friends', 'private'] as const).map(v => (
                    <button
                      key={v}
                      onClick={() => update('visibility', v)}
                      style={{
                        flex: 1,
                        background: form.visibility === v ? 'var(--accent-soft)' : 'var(--elevated)',
                        border: `1px solid ${form.visibility === v ? 'var(--accent-border)' : 'var(--border)'}`,
                        borderRadius: 10,
                        padding: '10px',
                        cursor: 'pointer',
                        fontSize: 13,
                        color: form.visibility === v ? 'var(--accent)' : 'var(--text-2)',
                        fontWeight: form.visibility === v ? 600 : 400,
                        textTransform: 'capitalize',
                      }}
                    >
                      {v}
                    </button>
                  ))}
                </div>
              </Field>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 16px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12 }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--text)' }}>Identity Lock</div>
                  <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>Marks this character as canon — others cannot replicate them</div>
                </div>
                <button
                  onClick={() => update('identityLocked', !form.identityLocked)}
                  style={{
                    width: 44,
                    height: 24,
                    borderRadius: 12,
                    background: form.identityLocked ? 'var(--accent)' : 'var(--elevated)',
                    border: `1px solid ${form.identityLocked ? 'var(--accent)' : 'var(--border-md)'}`,
                    cursor: 'pointer',
                    position: 'relative',
                    flexShrink: 0,
                    transition: 'all 200ms ease',
                  }}
                >
                  <div style={{
                    position: 'absolute',
                    top: 2,
                    left: form.identityLocked ? 'calc(100% - 22px)' : 2,
                    width: 18,
                    height: 18,
                    borderRadius: '50%',
                    background: '#fff',
                    transition: 'left 200ms ease',
                    boxShadow: '0 1px 4px rgba(0,0,0,0.2)',
                  }} />
                </button>
              </div>
            </div>
          )}

          {/* Step 1: Appearance */}
          {step === 1 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
              <Field label="Portrait image URL" hint="A direct link to a portrait image">
                <input
                  value={form.portraitUrl}
                  onChange={e => update('portraitUrl', e.target.value)}
                  placeholder="https://…"
                  style={inputStyle}
                />
                {form.portraitUrl && (
                  <div style={{ marginTop: 10, width: 72, height: 72, borderRadius: 14, overflow: 'hidden', border: '2px solid var(--border-md)' }}>
                    <img src={form.portraitUrl} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  </div>
                )}
              </Field>
              <Field label="Cover / banner image URL" hint="Cinematic backdrop for their profile page">
                <input
                  value={form.coverUrl}
                  onChange={e => update('coverUrl', e.target.value)}
                  placeholder="https://…"
                  style={inputStyle}
                />
              </Field>
              <Field label="Apparent age">
                <input
                  value={form.age}
                  onChange={e => update('age', e.target.value)}
                  placeholder="e.g. Mid-30s, Ageless, 1,247 years"
                  style={inputStyle}
                />
              </Field>
              <Field label="Physical notes" hint="How others see them — describe freely">
                <textarea
                  value={form.physicalNotes}
                  onChange={e => update('physicalNotes', e.target.value)}
                  placeholder="Tall, weathered hands. Brown hair gone grey at the temples. Prefers dark clothing without ornamentation."
                  style={{ ...inputStyle, minHeight: 90, resize: 'vertical' }}
                />
              </Field>
            </div>
          )}

          {/* Step 2: Backstory */}
          {step === 2 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
              <Field label="Origin" hint="Where they began — not necessarily where they are now">
                <textarea
                  value={form.backstory}
                  onChange={e => update('backstory', e.target.value)}
                  placeholder="Write freely. Fragments, not facts. You can revise this as they grow."
                  style={{ ...inputStyle, minHeight: 180, resize: 'vertical', fontFamily: 'var(--font-serif)', fontSize: 16, lineHeight: 1.75 }}
                />
              </Field>
            </div>
          )}

          {/* Step 3: Voice */}
          {step === 3 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
              <Field label="Voice & tone" hint="How they communicate — not just vocabulary, but manner">
                <textarea
                  value={form.voice}
                  onChange={e => update('voice', e.target.value)}
                  placeholder="Measured. Unhurried. Uses the second person rarely. Quotes weather more often than history."
                  style={{ ...inputStyle, minHeight: 110, resize: 'vertical' }}
                />
              </Field>
              <Field label="Quirks, habits, tells" hint="What makes them unmistakably themselves">
                <textarea
                  value={form.quirks}
                  onChange={e => update('quirks', e.target.value)}
                  placeholder="Always has soil under two fingernails. Addresses difficult conversations by looking at something nearby — a window, a cup — rather than at the person."
                  style={{ ...inputStyle, minHeight: 110, resize: 'vertical' }}
                />
              </Field>
            </div>
          )}

          {/* Step 4: World */}
          {step === 4 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
              <Field label="Realm" hint="The world they inhabit — their home context">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 10 }}>
                  {REALM_OPTIONS.map(r => (
                    <button
                      key={r}
                      onClick={() => update('realm', r)}
                      style={{
                        background: form.realm === r ? 'var(--accent-soft)' : 'var(--elevated)',
                        border: `1px solid ${form.realm === r ? 'var(--accent-border)' : 'var(--border)'}`,
                        borderRadius: 10,
                        padding: '11px 16px',
                        cursor: 'pointer',
                        fontSize: 13.5,
                        color: form.realm === r ? 'var(--accent)' : 'var(--text-2)',
                        fontWeight: form.realm === r ? 600 : 400,
                        textAlign: 'left',
                        transition: 'all 150ms ease',
                      }}
                    >
                      {r}
                    </button>
                  ))}
                </div>
              </Field>
              <Field label="Lore notes" hint="Private canon — things only you know (not shown publicly)">
                <textarea
                  value={form.loreNotes}
                  onChange={e => update('loreNotes', e.target.value)}
                  placeholder="Has never spoken of his parents. Arrived in the Verdant Coast during the year of the storm without explanation."
                  style={{ ...inputStyle, minHeight: 110, resize: 'vertical' }}
                />
              </Field>
            </div>
          )}

          {/* Navigation */}
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 48, paddingTop: 24, borderTop: '1px solid var(--border)' }}>
            <button
              onClick={() => step > 0 ? setStep(s => s - 1) : onNavigate('home')}
              style={{
                background: 'var(--elevated)',
                border: '1px solid var(--border)',
                borderRadius: 10,
                padding: '11px 24px',
                cursor: 'pointer',
                color: 'var(--text-2)',
                fontSize: 13,
                fontWeight: 500,
              }}
            >
              {step === 0 ? 'Cancel' : '← Back'}
            </button>
            <button
              onClick={() => step < STEPS.length - 1 ? setStep(s => s + 1) : handleSubmit()}
              disabled={step === 0 && !form.name.trim()}
              style={{
                background: 'var(--accent)',
                border: 'none',
                borderRadius: 10,
                padding: '11px 28px',
                cursor: step === 0 && !form.name.trim() ? 'not-allowed' : 'pointer',
                color: '#fff',
                fontSize: 13,
                fontWeight: 600,
                opacity: step === 0 && !form.name.trim() ? 0.45 : 1,
              }}
            >
              {step < STEPS.length - 1 ? 'Continue →' : 'Create Character'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function Field({ label, hint, required, children }: { label: string; hint?: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <label style={{ display: 'block', marginBottom: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>
          {label}
          {required && <span style={{ color: 'var(--accent)', marginLeft: 4 }}>*</span>}
        </span>
        {hint && <span style={{ fontSize: 12, color: 'var(--text-3)', marginLeft: 8 }}>{hint}</span>}
      </label>
      {children}
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  background: 'var(--elevated)',
  border: '1px solid var(--border-md)',
  borderRadius: 10,
  padding: '11px 14px',
  fontSize: 14,
  color: 'var(--text)',
  fontFamily: 'var(--font-sans)',
  outline: 'none',
  lineHeight: 1.5,
}
