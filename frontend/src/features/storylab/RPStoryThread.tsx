import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type {
  RPStoryThreadDetail,
  RPStoryTurn,
  GenerateThreadReplyResponse,
  Character,
  RPReplyIntensity,
  RPReplyResponseLength,
} from '@/lib/types';

const IS_INTERNAL =
  import.meta.env.VITE_INTERNAL_TESTING === 'true' || import.meta.env.DEV === true;

interface Props {
  threadId: number;
}

type PanelTheme = 'dark' | 'light';

function TurnCard({
  turn,
  charName,
  partnerLabel,
  theme,
}: {
  turn: RPStoryTurn;
  charName: string;
  partnerLabel: string;
  theme: PanelTheme;
}) {
  const isCharacter = turn.author_type === 'selected_character';
  const label = isCharacter ? charName || 'Your Character' : partnerLabel || 'Partner';

  return (
    <div className={`flex ${isCharacter ? 'justify-end' : 'justify-start'} mb-4`}>
      <div className={`max-w-[85%] rounded-xl p-4 border ${
        isCharacter
          ? 'border-gem/30 bg-gem/[0.06]'
          : 'border-edge-md bg-black/20'
      } ${theme === 'dark' ? 'text-white' : ''}`}>
        <div className="flex items-center gap-2 mb-2">
          <span className={`text-xs font-semibold tracking-wide uppercase ${
            isCharacter ? 'text-gem' : 'text-ink-2'
          }`}>
            {label}
          </span>
          {isCharacter && turn.generated && (
            <span className="text-[10px] text-ink-3 bg-surface-elevated px-1.5 py-0.5 rounded">AI</span>
          )}
          {IS_INTERNAL && turn.godmod_detected && (
            <span className="text-[10px] text-amber-400 bg-amber-950/50 px-1.5 py-0.5 rounded">
              godmod:{turn.godmod_severity}
            </span>
          )}
        </div>
        <div className={`whitespace-pre-wrap text-sm leading-relaxed ${
          theme === 'dark'
            ? (isCharacter ? 'text-emerald-50' : 'text-ink')
            : (isCharacter ? 'text-emerald-900' : 'text-gray-800')
        }`}>
          {turn.content}
        </div>
      </div>
    </div>
  );
}

export default function RPStoryThread({ threadId }: Props) {
  const navigate = useNavigate();
  const bottomRef = useRef<HTMLDivElement>(null);

  const [thread, setThread] = useState<RPStoryThreadDetail | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // generation state
  const [generating, setGenerating] = useState(false);
  const [draft, setDraft] = useState<GenerateThreadReplyResponse | null>(null);
  const [draftText, setDraftText] = useState('');
  const [saving, setSaving] = useState(false);
  const [genError, setGenError] = useState('');

  // partner reply input
  const [partnerInput, setPartnerInput] = useState('');
  const [addingPartner, setAddingPartner] = useState(false);
  const [partnerError, setPartnerError] = useState('');

  // gen controls
  const [intensity, setIntensity] = useState<RPReplyIntensity>('standard');
  const [responseLength, setResponseLength] = useState<RPReplyResponseLength>('match');
  const [instructions, setInstructions] = useState('');

  // panel theme
  const [theme, setTheme] = useState<PanelTheme>('dark');

  useEffect(() => {
    Promise.all([
      apiClient.getRPStory(threadId),
      apiClient.getCharacters(),
    ])
      .then(([t, chars]) => {
        setThread(t);
        setCharacters(chars);
      })
      .catch(() => setError('Failed to load thread.'))
      .finally(() => setLoading(false));
  }, [threadId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [thread?.turns]);

  const selectedChar = characters.find(c => c.id === thread?.selected_character_id);

  const lastTurn = thread?.turns[thread.turns.length - 1];
  const lastTurnIsPartner = lastTurn?.author_type === 'partner';
  const lastTurnIsCharacter = lastTurn?.author_type === 'selected_character';

  async function handleGenerate() {
    if (!thread) return;
    setGenerating(true);
    setGenError('');
    setDraft(null);
    try {
      const result = await apiClient.generateThreadReply(thread.id, {
        response_length: responseLength,
        intensity,
        instructions: instructions || undefined,
      });
      setDraft(result);
      setDraftText(result.reply);
    } catch (e: unknown) {
      setGenError(e instanceof Error ? e.message : 'Generation failed.');
    } finally {
      setGenerating(false);
    }
  }

  async function handleSave() {
    if (!thread || !draft) return;
    setSaving(true);
    try {
      const saved = await apiClient.saveGeneratedTurn(thread.id, {
        content: draftText,
        godmod_detected: draft.godmod_detected,
        godmod_severity: draft.godmod_severity,
        godmod_warnings: draft.godmod_warnings,
        model_used: draft.model_used,
        generation_time_ms: draft.generation_time_ms,
      });
      setThread(prev => prev
        ? { ...prev, turns: [...prev.turns, saved], turn_count: prev.turn_count + 1 }
        : prev
      );
      setDraft(null);
      setDraftText('');
    } catch (e: unknown) {
      setGenError(e instanceof Error ? e.message : 'Save failed.');
    } finally {
      setSaving(false);
    }
  }

  async function handleAddPartnerTurn() {
    if (!thread || !partnerInput.trim()) return;
    setAddingPartner(true);
    setPartnerError('');
    try {
      const turn = await apiClient.addPartnerTurn(thread.id, { content: partnerInput.trim() });
      setThread(prev => prev
        ? { ...prev, turns: [...prev.turns, turn], turn_count: prev.turn_count + 1 }
        : prev
      );
      setPartnerInput('');
    } catch (e: unknown) {
      setPartnerError(e instanceof Error ? e.message : 'Failed to save partner reply.');
    } finally {
      setAddingPartner(false);
    }
  }

  async function handleArchive() {
    if (!thread) return;
    if (!confirm('Archive this thread?')) return;
    await apiClient.archiveRPStory(thread.id);
    navigate('/rp-stories');
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-app flex items-center justify-center">
        <span className="text-ink-3 text-sm">Loading…</span>
      </div>
    );
  }

  if (error || !thread) {
    return (
      <div className="min-h-screen bg-app flex items-center justify-center">
        <span className="text-red-400 text-sm">{error || 'Thread not found.'}</span>
      </div>
    );
  }

  const partnerLabel = thread.partner_label || 'Partner';
  const charName = selectedChar?.name || 'Your Character';

  return (
    <div className="min-h-screen bg-app text-ink flex flex-col">

      {/* Header */}
      <div className="sticky top-0 z-10 bg-app backdrop-blur border-b border-edge px-4 py-3">
        <div className="max-w-3xl mx-auto flex items-center gap-3">
          <button
            onClick={() => navigate('/rp-stories')}
            className="text-ink-3 hover:text-ink-2 text-sm transition-colors"
          >
            ← Threads
          </button>
          <div className="flex-1 min-w-0">
            <h1 className="font-serif text-lg font-medium text-ink truncate">{thread.title}</h1>
            <p className="text-xs text-ink-3">
              {partnerLabel} · {thread.turn_count} turn{thread.turn_count !== 1 ? 's' : ''} ·{' '}
              {charName}
            </p>
          </div>
          {/* Theme toggles */}
          <div className="flex gap-1.5 shrink-0">
            <button
              onClick={() => setTheme('dark')}
              title="Dark reading panel"
              className={`w-7 h-7 rounded-md border text-xs font-bold transition-colors ${
                theme === 'dark'
                  ? 'border-gem/50 text-gem bg-gem/[0.06]'
                  : 'border-edge-md text-ink-3 hover:border-gray-500'
              }`}
            >
              ◾
            </button>
            <button
              onClick={() => setTheme('light')}
              title="Light reading panel"
              className={`w-7 h-7 rounded-md border text-xs font-bold transition-colors ${
                theme === 'light'
                  ? 'border-gray-300 text-gray-900 bg-white'
                  : 'border-edge-md text-ink-2 hover:border-gray-500'
              }`}
            >
              ◽
            </button>
          </div>
          {thread.status === 'active' && (
            <button
              onClick={handleArchive}
              className="text-ink-3 hover:text-ink-2 text-xs transition-colors shrink-0"
            >
              Archive
            </button>
          )}
        </div>
      </div>

      {/* Thread archived banner */}
      {thread.status === 'archived' && (
        <div className="bg-surface border-b border-edge-md px-4 py-2 text-center">
          <span className="text-xs text-ink-3">This thread is archived — read-only.</span>
        </div>
      )}

      {/* Turns timeline */}
      <div className={`flex-1 px-4 py-6 ${theme === 'light' ? 'bg-gray-100' : ''}`}>
        <div className="max-w-3xl mx-auto">
          {thread.turns.length === 0 && (
            <p className="text-center text-ink-3 text-sm py-12">No turns yet.</p>
          )}
          {thread.turns.map(turn => (
            <TurnCard
              key={turn.id}
              turn={turn}
              charName={charName}
              partnerLabel={partnerLabel}
              theme={theme}
            />
          ))}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Action area — only when active */}
      {thread.status === 'active' && (
        <div className="border-t border-edge bg-app backdrop-blur">
          <div className="max-w-3xl mx-auto px-4 py-5 space-y-5">

            {/* Draft area */}
            {draft && (
              <div className="rounded-xl border border-gem/30 bg-gem/[0.06] p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gem uppercase tracking-wide">
                    {charName} — Draft
                  </span>
                  <div className="flex gap-2 text-xs">
                    {IS_INTERNAL && (
                      <span className="text-ink-3">{draft.model_used} · {draft.generation_time_ms}ms</span>
                    )}
                    {draft.godmod_detected && !IS_INTERNAL && (
                      <span className="text-amber-400">Your character stayed in control.</span>
                    )}
                    {IS_INTERNAL && draft.godmod_detected && (
                      <span className="text-amber-400">godmod:{draft.godmod_severity}</span>
                    )}
                  </div>
                </div>
                <textarea
                  value={draftText}
                  onChange={e => setDraftText(e.target.value)}
                  rows={8}
                  className="w-full rounded-lg bg-black/40 border border-edge-md text-ink text-sm p-3 resize-y focus:outline-none focus:border-gem/50 leading-relaxed"
                />
                {IS_INTERNAL && draft.godmod_warnings.length > 0 && (
                  <div className="text-xs text-amber-400/80 space-y-0.5">
                    {draft.godmod_warnings.map((w, i) => <p key={i}>{w}</p>)}
                  </div>
                )}
                <div className="flex gap-2">
                  <button
                    onClick={handleSave}
                    disabled={saving || !draftText.trim()}
                    className="px-4 py-2 rounded-lg bg-gem hover:bg-gem disabled:opacity-40 text-gem-ink text-sm font-medium transition-colors"
                  >
                    {saving ? 'Saving…' : 'Save Reply'}
                  </button>
                  <button
                    onClick={handleGenerate}
                    disabled={generating}
                    className="px-4 py-2 rounded-lg border border-edge-md hover:border-gray-500 text-ink-2 text-sm transition-colors"
                  >
                    Regenerate
                  </button>
                  <button
                    onClick={() => { setDraft(null); setDraftText(''); }}
                    className="px-4 py-2 rounded-lg border border-edge hover:border-edge-md text-ink-3 text-sm transition-colors"
                  >
                    Discard
                  </button>
                </div>
              </div>
            )}

            {/* Generate controls — show when last turn is partner */}
            {!draft && lastTurnIsPartner && thread.selected_character_id && (
              <div className="rounded-xl border border-edge bg-surface p-4 space-y-3">
                <p className="text-xs font-semibold text-ink-2 uppercase tracking-wide">
                  Generate {charName}'s Reply
                </p>
                <div className="flex flex-wrap gap-3">
                  <div>
                    <label className="text-xs text-ink-3 block mb-1">Length</label>
                    <select
                      value={responseLength}
                      onChange={e => setResponseLength(e.target.value as RPReplyResponseLength)}
                      className="bg-surface-elevated border border-edge-md rounded-lg text-sm text-ink px-2 py-1.5 focus:outline-none focus:border-gem/50"
                    >
                      <option value="short">Short</option>
                      <option value="match">Match</option>
                      <option value="long">Long</option>
                      <option value="novella">Novella</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-ink-3 block mb-1">Intensity</label>
                    <select
                      value={intensity}
                      onChange={e => setIntensity(e.target.value as RPReplyIntensity)}
                      className="bg-surface-elevated border border-edge-md rounded-lg text-sm text-ink px-2 py-1.5 focus:outline-none focus:border-gem/50"
                    >
                      <option value="standard">Standard</option>
                      <option value="mature">Mature</option>
                      <option value="explicit">Explicit</option>
                    </select>
                  </div>
                </div>
                <textarea
                  value={instructions}
                  onChange={e => setInstructions(e.target.value)}
                  placeholder="Optional guidance for this reply…"
                  rows={2}
                  maxLength={2000}
                  className="w-full rounded-lg bg-surface-elevated border border-edge-md text-ink text-sm p-2.5 resize-none focus:outline-none focus:border-gem/50 placeholder:text-ink-3"
                />
                {genError && <p className="text-red-400 text-xs">{genError}</p>}
                <button
                  onClick={handleGenerate}
                  disabled={generating}
                  className="w-full py-2.5 rounded-lg bg-gem hover:bg-gem disabled:opacity-40 text-gem-ink text-sm font-medium transition-colors"
                >
                  {generating ? 'Generating…' : `Generate ${charName}'s Reply`}
                </button>
              </div>
            )}

            {!draft && lastTurnIsPartner && !thread.selected_character_id && (
              <p className="text-center text-ink-3 text-xs py-2">
                No character selected for this thread. Create a new thread with a character to generate replies.
              </p>
            )}

            {/* Add partner turn — show when last turn is character (or thread is new with no character turns yet after saving) */}
            {!draft && lastTurnIsCharacter && (
              <div className="rounded-xl border border-edge bg-surface p-4 space-y-3">
                <p className="text-xs font-semibold text-ink-3 uppercase tracking-wide">
                  Paste {partnerLabel}'s Reply
                </p>
                <textarea
                  value={partnerInput}
                  onChange={e => setPartnerInput(e.target.value)}
                  placeholder={`Paste ${partnerLabel}'s next reply here…`}
                  rows={5}
                  maxLength={20000}
                  className="w-full rounded-lg bg-surface-elevated border border-edge-md text-ink text-sm p-3 resize-y focus:outline-none focus:border-edge-md placeholder:text-ink-3 leading-relaxed"
                />
                {partnerError && <p className="text-red-400 text-xs">{partnerError}</p>}
                <button
                  onClick={handleAddPartnerTurn}
                  disabled={addingPartner || !partnerInput.trim()}
                  className="px-4 py-2 rounded-lg bg-surface-overlay hover:bg-surface-overlay disabled:opacity-40 text-ink text-sm font-medium transition-colors"
                >
                  {addingPartner ? 'Saving…' : `Add ${partnerLabel}'s Reply`}
                </button>
              </div>
            )}

          </div>
        </div>
      )}
    </div>
  );
}
