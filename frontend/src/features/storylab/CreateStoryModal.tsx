/**
 * CreateStoryModal — 3-step story creation ritual.
 *
 * Step 1: Identity  — title, genre, premise
 * Step 2: World     — optional realm picker
 * Step 3: Cast      — optional character picker (up to 4)
 *
 * On success, calls onCreated(storyId) so the parent can navigate.
 */
import { useState, useEffect, useCallback } from 'react';
import { apiClient } from '@/lib/apiClient';
import type { Realm, Character } from '@/lib/types';

// ── constants ──────────────────────────────────────────────────────────────────

const GENRES = [
  'Literary', 'Romance', 'Fantasy', 'Thriller',
  'Horror', 'Adventure', 'Sci-Fi', 'Mystery', 'Other',
];

const COVER_COLORS = [
  '#1a1a2e', '#16213e', '#0f3460', '#1b1b2f',
  '#2c1810', '#1a2a1a', '#2a1a2e', '#1e2a1e',
];

const MAX_CAST = 4;

// ── helpers ────────────────────────────────────────────────────────────────────

function hashColor(title: string): string {
  let h = 0;
  for (let i = 0; i < title.length; i++) h = (h * 31 + title.charCodeAt(i)) & 0xffffffff;
  return COVER_COLORS[Math.abs(h) % COVER_COLORS.length];
}

// ── sub-components ─────────────────────────────────────────────────────────────

function StepDots({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center gap-1.5">
      {Array.from({ length: total }).map((_, i) => (
        <div
          key={i}
          className={`h-1.5 rounded-full transition-all duration-200 ${
            i === current ? 'w-5 bg-emerald-500' : i < current ? 'w-1.5 bg-emerald-700/60' : 'w-1.5 bg-gray-700'
          }`}
        />
      ))}
    </div>
  );
}

// ── main component ─────────────────────────────────────────────────────────────

interface Props {
  onCreated: (storyId: string) => void;
  onCancel: () => void;
}

export default function CreateStoryModal({ onCreated, onCancel }: Props) {
  // ── step state ─────────────────────────────────────────────────────────────

  const [step, setStep] = useState(0); // 0=Identity, 1=World, 2=Cast

  // ── Step 1 ─────────────────────────────────────────────────────────────────

  const [title, setTitle]   = useState('');
  const [genre, setGenre]   = useState('');
  const [premise, setPremise] = useState('');
  const [coverColor, setCoverColor] = useState(COVER_COLORS[0]);

  // Auto-pick cover color from title
  useEffect(() => {
    if (title.trim()) setCoverColor(hashColor(title.trim()));
  }, [title]);

  // ── Step 2 ─────────────────────────────────────────────────────────────────

  const [realms, setRealms]         = useState<Realm[]>([]);
  const [realmSearch, setRealmSearch] = useState('');
  const [selectedRealm, setSelectedRealm] = useState<Realm | null>(null);
  const [loadingRealms, setLoadingRealms] = useState(false);

  const fetchRealms = useCallback(async () => {
    setLoadingRealms(true);
    try {
      // Fetch user's owned + member realms (public_only=false to include private)
      const data = await apiClient.getRealms(undefined, false);
      setRealms(data);
    } catch {
      // non-fatal
    } finally {
      setLoadingRealms(false);
    }
  }, []);

  useEffect(() => {
    if (step === 1) void fetchRealms();
  }, [step, fetchRealms]);

  const filteredRealms = realms.filter((r) =>
    r.name.toLowerCase().includes(realmSearch.toLowerCase()),
  );

  // ── Step 3 ─────────────────────────────────────────────────────────────────

  const [characters, setCharacters]   = useState<Character[]>([]);
  const [castIds, setCastIds]          = useState<number[]>([]);
  const [loadingChars, setLoadingChars] = useState(false);

  const fetchCharacters = useCallback(async () => {
    setLoadingChars(true);
    try {
      const data = await apiClient.getCharacters();
      setCharacters(data);
    } catch {
      // non-fatal
    } finally {
      setLoadingChars(false);
    }
  }, []);

  useEffect(() => {
    if (step === 2) void fetchCharacters();
  }, [step, fetchCharacters]);

  function toggleCast(id: number) {
    setCastIds((prev) =>
      prev.includes(id)
        ? prev.filter((x) => x !== id)
        : prev.length < MAX_CAST
          ? [...prev, id]
          : prev,
    );
  }

  // ── Submit ─────────────────────────────────────────────────────────────────

  const [submitting, setSubmitting] = useState(false);
  const [error, setError]           = useState('');

  async function handleCreate() {
    if (!title.trim()) return;
    setSubmitting(true);
    setError('');
    try {
      const story = await apiClient.createStory({
        title: title.trim(),
        genre: genre || undefined,
        premise: premise.trim() || undefined,
        realm_id: selectedRealm?.id ?? null,
        character_ids: castIds,
        cover_color: coverColor,
      });
      onCreated(story.id);
    } catch (err) {
      setError((err as Error).message || 'Could not create story. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  // ── Keyboard ───────────────────────────────────────────────────────────────

  function handleBackdropKey(e: React.KeyboardEvent) {
    if (e.key === 'Escape') onCancel();
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  const canAdvanceStep1 = title.trim().length > 0;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onKeyDown={handleBackdropKey}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onCancel}
      />

      {/* Panel */}
      <div className="relative z-10 w-full max-w-md bg-gray-950 border border-gray-800 rounded-2xl shadow-2xl flex flex-col overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-5 pb-4 border-b border-gray-800/60">
          <div>
            <h2 className="text-base font-semibold text-gray-100">New Story</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {step === 0 && 'Give your story an identity'}
              {step === 1 && 'Set the world (optional)'}
              {step === 2 && 'Add characters (optional)'}
            </p>
          </div>
          <StepDots current={step} total={3} />
        </div>

        {/* Body */}
        <div className="px-6 py-5 flex-1 overflow-y-auto space-y-4">

          {/* ── Step 0: Identity ──────────────────────────────────────────── */}
          {step === 0 && (
            <>
              {/* Cover color + title row */}
              <div className="flex items-start gap-3">
                <div
                  className="w-10 h-10 rounded-xl shrink-0 border border-gray-700/60 mt-0.5"
                  style={{ backgroundColor: coverColor }}
                />
                <div className="flex-1">
                  <input
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Story title"
                    maxLength={200}
                    autoFocus
                    className="w-full bg-transparent text-gray-100 text-base font-semibold placeholder-gray-600 focus:outline-none border-b border-gray-800 pb-1.5 focus:border-gray-600 transition"
                  />
                  <p className="text-[10px] text-gray-700 mt-1">{title.length}/200</p>
                </div>
              </div>

              {/* Cover color picker */}
              <div>
                <p className="text-xs text-gray-500 mb-2">Cover color</p>
                <div className="flex gap-2">
                  {COVER_COLORS.map((c) => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setCoverColor(c)}
                      className={`w-6 h-6 rounded-lg border-2 transition ${
                        coverColor === c ? 'border-emerald-400 scale-110' : 'border-transparent hover:border-gray-600'
                      }`}
                      style={{ backgroundColor: c }}
                    />
                  ))}
                </div>
              </div>

              {/* Genre */}
              <div>
                <p className="text-xs text-gray-500 mb-2">Genre</p>
                <div className="flex flex-wrap gap-1.5">
                  {GENRES.map((g) => (
                    <button
                      key={g}
                      type="button"
                      onClick={() => setGenre(genre === g.toLowerCase() ? '' : g.toLowerCase())}
                      className={`px-2.5 py-1 text-xs rounded-lg border transition ${
                        genre === g.toLowerCase()
                          ? 'bg-emerald-600/30 border-emerald-500/60 text-emerald-300'
                          : 'bg-gray-900/40 border-gray-700/60 text-gray-400 hover:border-gray-600 hover:text-gray-300'
                      }`}
                    >
                      {g}
                    </button>
                  ))}
                </div>
              </div>

              {/* Premise */}
              <div>
                <p className="text-xs text-gray-500 mb-2">Opening premise <span className="text-gray-700">(optional)</span></p>
                <textarea
                  value={premise}
                  onChange={(e) => setPremise(e.target.value)}
                  placeholder="What's the spark? A sentence or two is fine."
                  rows={3}
                  maxLength={1000}
                  className="w-full resize-none rounded-xl bg-gray-900/60 border border-gray-800/70 p-3 text-sm text-gray-200 placeholder-gray-700 focus:outline-none focus:border-gray-600 transition leading-relaxed"
                />
              </div>
            </>
          )}

          {/* ── Step 1: World ─────────────────────────────────────────────── */}
          {step === 1 && (
            <>
              <p className="text-xs text-gray-500 leading-relaxed">
                Bind your story to one of your realms to pull in its lore and setting.
              </p>

              <input
                type="text"
                value={realmSearch}
                onChange={(e) => setRealmSearch(e.target.value)}
                placeholder="Search realms…"
                className="w-full rounded-xl bg-gray-900/60 border border-gray-800/70 px-3 py-2 text-sm text-gray-200 placeholder-gray-700 focus:outline-none focus:border-gray-600 transition"
              />

              {loadingRealms ? (
                <div className="space-y-2">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-10 bg-gray-900/60 rounded-xl animate-pulse" />
                  ))}
                </div>
              ) : filteredRealms.length === 0 ? (
                <p className="text-xs text-gray-600 text-center py-4">
                  {realms.length === 0 ? 'No realms yet — you can skip this.' : 'No matching realms.'}
                </p>
              ) : (
                <div className="space-y-1.5 max-h-52 overflow-y-auto">
                  {/* None option */}
                  <button
                    type="button"
                    onClick={() => setSelectedRealm(null)}
                    className={`w-full text-left px-3 py-2.5 rounded-xl border text-sm transition ${
                      selectedRealm === null
                        ? 'border-emerald-500/50 bg-emerald-900/20 text-emerald-300'
                        : 'border-gray-800/60 bg-gray-900/40 text-gray-500 hover:border-gray-700 hover:text-gray-400'
                    }`}
                  >
                    Original world (no realm)
                  </button>
                  {filteredRealms.map((r) => (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() => setSelectedRealm(r)}
                      className={`w-full text-left px-3 py-2.5 rounded-xl border transition ${
                        selectedRealm?.id === r.id
                          ? 'border-emerald-500/50 bg-emerald-900/20'
                          : 'border-gray-800/60 bg-gray-900/40 hover:border-gray-700'
                      }`}
                    >
                      <p className={`text-sm font-medium ${selectedRealm?.id === r.id ? 'text-emerald-300' : 'text-gray-300'}`}>
                        {r.name}
                      </p>
                      {r.tagline && (
                        <p className="text-[11px] text-gray-600 mt-0.5 truncate">{r.tagline}</p>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </>
          )}

          {/* ── Step 2: Cast ──────────────────────────────────────────────── */}
          {step === 2 && (
            <>
              <p className="text-xs text-gray-500 leading-relaxed">
                Add up to {MAX_CAST} of your characters. Their voice and traits will inform the story.
              </p>

              {loadingChars ? (
                <div className="space-y-2">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-12 bg-gray-900/60 rounded-xl animate-pulse" />
                  ))}
                </div>
              ) : characters.length === 0 ? (
                <p className="text-xs text-gray-600 text-center py-4">
                  No characters yet — you can skip this.
                </p>
              ) : (
                <div className="space-y-1.5 max-h-60 overflow-y-auto">
                  {characters.map((c) => {
                    const selected = castIds.includes(c.id);
                    const disabled = !selected && castIds.length >= MAX_CAST;
                    return (
                      <button
                        key={c.id}
                        type="button"
                        disabled={disabled}
                        onClick={() => toggleCast(c.id)}
                        className={`w-full text-left flex items-center gap-3 px-3 py-2.5 rounded-xl border transition ${
                          selected
                            ? 'border-emerald-500/50 bg-emerald-900/20'
                            : disabled
                              ? 'border-gray-800/40 bg-gray-900/20 opacity-40 cursor-not-allowed'
                              : 'border-gray-800/60 bg-gray-900/40 hover:border-gray-700'
                        }`}
                      >
                        {/* Avatar */}
                        <div className="w-8 h-8 rounded-full shrink-0 bg-gray-800 overflow-hidden flex items-center justify-center">
                          {c.avatar_url ? (
                            <img src={c.avatar_url} alt={c.name} className="w-full h-full object-cover" />
                          ) : (
                            <span className="text-xs text-gray-500">{c.name[0]}</span>
                          )}
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className={`text-sm font-medium truncate ${selected ? 'text-emerald-300' : 'text-gray-300'}`}>
                            {c.name}
                          </p>
                          {c.short_bio && (
                            <p className="text-[11px] text-gray-600 truncate">{c.short_bio}</p>
                          )}
                        </div>
                        {selected && (
                          <span className="text-emerald-500 text-xs shrink-0">✓</span>
                        )}
                      </button>
                    );
                  })}
                </div>
              )}

              {castIds.length > 0 && (
                <p className="text-[11px] text-gray-600">
                  {castIds.length}/{MAX_CAST} characters selected
                </p>
              )}
            </>
          )}

          {error && (
            <p className="text-xs text-red-400 bg-red-900/20 border border-red-700/40 rounded-lg px-3 py-2">
              {error}
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-800/60 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={step === 0 ? onCancel : () => setStep((s) => s - 1)}
            className="px-4 py-2 text-sm rounded-xl border border-gray-700/60 bg-gray-900/40 hover:bg-gray-800/50 hover:border-gray-600 text-gray-400 hover:text-gray-300 transition"
          >
            {step === 0 ? 'Cancel' : '← Back'}
          </button>

          {step < 2 ? (
            <button
              type="button"
              disabled={step === 0 && !canAdvanceStep1}
              onClick={() => setStep((s) => s + 1)}
              className="px-5 py-2 text-sm rounded-xl bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white font-semibold transition disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Next →
            </button>
          ) : (
            <button
              type="button"
              disabled={submitting || !canAdvanceStep1}
              onClick={() => void handleCreate()}
              className="px-5 py-2 text-sm rounded-xl bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white font-semibold transition disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {submitting ? 'Creating…' : 'Create Story →'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
