/**
 * StoryLabEngine — RedQuill-parity chapter-based writing panel.
 *
 * Each generation produces a NEW CHAPTER (fresh output), stored in the backend.
 * After generation, 3 continuation suggestions + a manual prompt box are shown.
 * Chapters are listed in a dropdown; each chapter has a prompt reveal.
 *
 * Story IDs are per-session strings stored in localStorage (unchanged).
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { apiClient } from '@/lib/apiClient';
import type { Character, StoryRecord } from '@/lib/types';

// ── Authenticated fetch helper ────────────────────────────────────────────────
// Attaches the JWT token stored by apiClient so StoryLab requests are
// authenticated the same way as every other part of the app.

function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = localStorage.getItem('token');
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string>),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return fetch(input, { ...init, headers, credentials: 'include' });
}

// ── localStorage keys ─────────────────────────────────────────────────────────

const LS_CURRENT  = 'ficshon_storylab_current_story_id';
const LS_RECENTS  = 'ficshon_storylab_recent_story_ids';
const SURFACE_KEY = 'fic_surface_mode';

// ── Story-ID helpers ──────────────────────────────────────────────────────────

function makeStoryId(): string {
  const now = new Date();
  const pad = (n: number, len = 2) => String(n).padStart(len, '0');
  const ts  = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const rand = Math.random().toString(36).slice(2, 7);
  return `storylab:${ts}-${rand}`;
}

function loadRecents(): string[] {
  try {
    const raw = localStorage.getItem(LS_RECENTS);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function addToRecents(id: string, current: string[]): string[] {
  const updated = [id, ...current.filter((r) => r !== id)].slice(0, 5);
  localStorage.setItem(LS_RECENTS, JSON.stringify(updated));
  return updated;
}

function formatStoryId(id: string): string {
  const m = id.match(/storylab:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})/);
  if (!m) return id;
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${months[parseInt(m[2]) - 1]} ${parseInt(m[3])}, ${m[4]}:${m[5]}`;
}

// ── Types ─────────────────────────────────────────────────────────────────────

type ChapterListItem = {
  chapter_number: number;
  created_at: string;
  words: number;
  mode: string;
  boundary: string;
  length: string;
};

type ChapterDetail = {
  chapter_number: number;
  generated_text: string;
  prompt_text: string;
  controls: Record<string, string>;
  suggestions: string[];
  words: number;
  created_at: string;
};

type SLControls = {
  direction: string;
  tone_intensity: string;
  pacing: string;
  length: string;
  boundary: string;
};

type SLStoryState = {
  tone: string;
  pacing: string;
  stakes: number | string;
  scene_type: string;
  intimacy_level: number;
  tension: number;
  emotional_weight: number;
};

// ── Beat types ────────────────────────────────────────────────────────────────

const BEAT_TYPES = [
  { id: "continue", label: "Continue tension" },
  { id: "escalate", label: "Escalate conflict" },
  { id: "reveal",   label: "Reveal something" },
  { id: "shift",    label: "Shift perspective" },
  { id: "slow",     label: "Slow the moment" },
  { id: "end",      label: "End the scene" },
] as const;

type BeatTypeId = typeof BEAT_TYPES[number]['id'];

// ── Beat actions ──────────────────────────────────────────────────────────────

type BeatAction = {
  label: string;
  hint: string;
  direction: string;
  pacing: string;
  length: string;
  beat_type: BeatTypeId;
  tone_intensity?: string;
};

// ── Support characters (creation view, local-only) ────────────────────────────

type SupportChar = {
  id: string;
  name: string;
  age: string;
  personality: string;
};

const BEAT_ACTIONS: BeatAction[] = [
  { label: 'Continue',               hint: 'Advance the scene forward',        direction: 'advance_plot',     pacing: 'balanced', length: 'short', beat_type: 'continue' },
  { label: 'Complicate It',          hint: 'Add friction or conflict',          direction: 'argument_begins',  pacing: 'fast',     length: 'short', beat_type: 'escalate' },
  { label: 'Slow It Down',           hint: 'Interior moment — let it breathe',  direction: 'quiet_reflection', pacing: 'slow',     length: 'short', beat_type: 'slow' },
  { label: 'Reveal Something',       hint: 'Shift what the reader knows',       direction: 'twist_event',      pacing: 'balanced', length: 'short', beat_type: 'reveal' },
  { label: 'Turn the Conversation',  hint: 'Push the dialogue somewhere else',  direction: 'add_dialogue',     pacing: 'balanced', length: 'short', beat_type: 'shift' },
  { label: 'End the Scene',          hint: 'Close this moment, open the next',  direction: 'quiet_reflection', pacing: 'slow',     length: 'short', beat_type: 'end', tone_intensity: 'moderate' },
];

// ── Component ─────────────────────────────────────────────────────────────────

interface StoryLabEngineProps {
  /** When provided, the engine operates against this story ID instead of
   *  the localStorage-managed one. The story selector and "+ New story"
   *  button are hidden when this prop is set. */
  storyId?: string;
  /** Display name shown in the chapter header when storyId prop is set. */
  storyTitle?: string;
  /** Full story record — used to populate the creation view (protagonist, genre, etc.). */
  storyRecord?: StoryRecord;
}

export default function StoryLabEngine({ storyId: externalStoryId, storyTitle, storyRecord }: StoryLabEngineProps = {}) {
  // ── Story-ID state ─────────────────────────────────────────────────────────
  // When externalStoryId is provided, use it directly (named story flow).
  // Otherwise fall back to localStorage (legacy inline flow).

  const [currentStoryId, setCurrentStoryId] = useState<string>(() => {
    if (externalStoryId) return externalStoryId;
    const stored = localStorage.getItem(LS_CURRENT);
    if (stored) return stored;
    const id = makeStoryId();
    localStorage.setItem(LS_CURRENT, id);
    return id;
  });

  const [recentIds, setRecentIds] = useState<string[]>(() => loadRecents());

  // ── Chapter state ──────────────────────────────────────────────────────────

  const [chapters, setChapters] = useState<ChapterListItem[]>([]);
  const [currentChapter, setCurrentChapter] = useState<ChapterDetail | null>(null);
  const [isLoadingChapters, setIsLoadingChapters] = useState(false);
  const [isLoadingChapter, setIsLoadingChapter] = useState(false);

  // ── Generation state ───────────────────────────────────────────────────────

  const [promptInput, setPromptInput] = useState('');
  const [mode, setMode] = useState<'roleplay' | 'duet' | 'play'>('roleplay');
  const [slControls, setSlControls] = useState<SLControls>({
    direction: 'advance_plot',
    tone_intensity: 'moderate',
    pacing: 'balanced',
    length: 'medium',
    boundary: 'sfw',
  });
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState('');
  type GenStatus = 'idle' | 'generating' | 'success' | 'failed';
  const [genStatus, setGenStatus] = useState<GenStatus>('idle');

  // ── Creation view state ────────────────────────────────────────────────────

  const [protagonist, setProtagonist] = useState<Character | null>(null);
  const [supportChars, setSupportChars] = useState<SupportChar[]>([]);
  const [newSupportName, setNewSupportName] = useState('');
  const [newSupportAge, setNewSupportAge] = useState('');
  const [newSupportPersonality, setNewSupportPersonality] = useState('');

  // ── UI state ───────────────────────────────────────────────────────────────

  const [promptRevealOpen, setPromptRevealOpen] = useState(false);
  const [confirmAction, setConfirmAction] = useState<'delete' | 'regenerate' | null>(null);
  const [surfaceMode, setSurfaceMode] = useState<'night' | 'paper'>(
    () => (localStorage.getItem(SURFACE_KEY) as 'night' | 'paper') ?? 'night'
  );

  // Story progress state (from /state endpoint)
  const [storyState, setStoryState] = useState<SLStoryState | null>(null);
  const [isLoadingState, setIsLoadingState] = useState(false);

  const abortRef = useRef<AbortController | null>(null);

  // Persist surface mode preference
  useEffect(() => { localStorage.setItem(SURFACE_KEY, surfaceMode); }, [surfaceMode]);

  // ── Abort all in-flight requests ───────────────────────────────────────────

  function abortAll() {
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();
  }

  // ── API calls ───────────────────────────────────────────────────────────────

  const fetchChapters = useCallback(async (storyId: string) => {
    setIsLoadingChapters(true);
    setError('');
    try {
      const resp = await authFetch(
        `/api/storylab/chapters?story_id=${encodeURIComponent(storyId)}`,
        { signal: abortRef.current?.signal },
      );
      if (resp.status === 401) {
        // Token expired or missing — surface a clear message, do not show "Not authenticated"
        setError('Your session has expired. Please log in again.');
        return;
      }
      if (resp.status === 403) {
        // Stale or forbidden story_id (e.g. from a previous session/device).
        // Recover silently by creating a fresh story rather than surfacing an error.
        const freshId = makeStoryId();
        localStorage.setItem(LS_CURRENT, freshId);
        setCurrentStoryId(freshId);
        setRecentIds((prev) => addToRecents(freshId, prev));
        setChapters([]);
        setCurrentChapter(null);
        return;
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json() as ChapterListItem[];
      setChapters(data);
      // Auto-load the most recent chapter
      if (data.length > 0) {
        const latest = data[data.length - 1];
        void loadChapter(storyId, latest.chapter_number);
      } else {
        setCurrentChapter(null);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      setError('Could not load chapters.');
    } finally {
      setIsLoadingChapters(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function loadChapter(storyId: string, chapterNum: number) {
    setIsLoadingChapter(true);
    setPromptRevealOpen(false);
    setConfirmAction(null);
    try {
      const resp = await authFetch(
        `/api/storylab/chapters/${chapterNum}?story_id=${encodeURIComponent(storyId)}`,
        { signal: abortRef.current?.signal },
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json() as ChapterDetail;
      setCurrentChapter(data);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      setError('Could not load chapter.');
    } finally {
      setIsLoadingChapter(false);
    }
  }

  async function fetchStoryState(storyId: string) {
    setIsLoadingState(true);
    try {
      const resp = await authFetch(
        `/api/storylab/state?story_id=${encodeURIComponent(storyId)}`,
        { signal: abortRef.current?.signal },
      );
      if (!resp.ok) return;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data = await resp.json() as any;
      const ss = data?.state_json?.story_state as SLStoryState | undefined;
      if (ss) setStoryState(ss);
    } catch {
      // non-critical
    } finally {
      setIsLoadingState(false);
    }
  }

  async function handleGenerate(overrideControls?: Partial<SLControls>, beatType?: BeatTypeId | null) {
    const activeControls: SLControls = overrideControls
      ? { ...slControls, ...overrideControls }
      : slControls;
    setError('');
    setGenStatus('generating');
    setConfirmAction(null);
    setIsGenerating(true);
    try {
      const effectivePrompt = chapters.length === 0
        ? buildEffectivePrompt(promptInput, supportChars)
        : promptInput;
      const payload = {
        prompt: effectivePrompt,
        mode,
        controls: activeControls,
        beat_type: beatType ?? null,
      };
      const resp = await authFetch(
        `/api/storylab/chapters/generate?story_id=${encodeURIComponent(currentStoryId)}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          signal: abortRef.current?.signal,
        },
      );
      if (!resp.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const err = await resp.json().catch(() => ({})) as any;
        throw new Error(err?.detail?.message || err?.detail || `HTTP ${resp.status}`);
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data = await resp.json() as any;
      // Guard: blank or missing generated_text is treated as a failure, not a silent no-op
      if (!data.generated_text?.trim()) {
        throw new Error('Generation returned no text. Please try again.');
      }
      const newChapter: ChapterDetail = {
        chapter_number: data.chapter_number,
        generated_text: data.generated_text,
        prompt_text: data.prompt_text,
        controls: activeControls,
        suggestions: data.suggestions ?? [],
        words: data.meta?.words ?? 0,
        created_at: new Date().toISOString(),
      };
      setCurrentChapter(newChapter);
      setChapters((prev) => {
        const filtered = prev.filter((c) => c.chapter_number !== data.chapter_number);
        return [
          ...filtered,
          {
            chapter_number: data.chapter_number,
            created_at: newChapter.created_at,
            words: newChapter.words,
            mode,
            boundary: activeControls.boundary,
            length: activeControls.length,
          },
        ].sort((a, b) => a.chapter_number - b.chapter_number);
      });
      setPromptInput('');
      setGenStatus('success');
      // Refresh state for progress bars
      void fetchStoryState(currentStoryId);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      setError((err as Error).message || 'Generation failed.');
      setGenStatus('failed');
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleDelete() {
    if (!currentChapter) return;
    setConfirmAction(null);
    try {
      const resp = await authFetch(
        `/api/storylab/chapters/${currentChapter.chapter_number}?story_id=${encodeURIComponent(currentStoryId)}`,
        { method: 'DELETE', signal: abortRef.current?.signal },
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setChapters((prev) => prev.filter((c) => c.chapter_number !== currentChapter.chapter_number));
      // Load the previous chapter, or clear
      const remaining = chapters.filter((c) => c.chapter_number !== currentChapter.chapter_number);
      if (remaining.length > 0) {
        void loadChapter(currentStoryId, remaining[remaining.length - 1].chapter_number);
      } else {
        setCurrentChapter(null);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      setError('Delete failed.');
    }
  }

  async function handleRegenerate() {
    if (!currentChapter) return;
    setConfirmAction(null);
    setError('');
    setGenStatus('generating');
    setIsGenerating(true);
    try {
      const payload = {
        prompt: currentChapter.prompt_text,
        mode,
        controls: slControls,
      };
      const resp = await authFetch(
        `/api/storylab/chapters/${currentChapter.chapter_number}/regenerate?story_id=${encodeURIComponent(currentStoryId)}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          signal: abortRef.current?.signal,
        },
      );
      if (!resp.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const err = await resp.json().catch(() => ({})) as any;
        throw new Error(err?.detail?.message || err?.detail || `HTTP ${resp.status}`);
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data = await resp.json() as any;
      if (!data.generated_text?.trim()) {
        throw new Error('Regeneration returned no text. Please try again.');
      }
      setCurrentChapter((prev) =>
        prev ? { ...prev, generated_text: data.generated_text, suggestions: data.suggestions ?? prev.suggestions, words: data.meta?.words ?? prev.words } : prev
      );
      setChapters((prev) =>
        prev.map((c) =>
          c.chapter_number === currentChapter.chapter_number
            ? { ...c, words: data.meta?.words ?? c.words }
            : c
        )
      );
      setGenStatus('success');
      void fetchStoryState(currentStoryId);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      setError((err as Error).message || 'Regeneration failed.');
      setGenStatus('failed');
    } finally {
      setIsGenerating(false);
    }
  }

  // ── Beat action handler ────────────────────────────────────────────────────

  function handleBeatAction(action: BeatAction) {
    void handleGenerate({
      direction: action.direction,
      pacing: action.pacing,
      length: action.length,
      ...(action.tone_intensity ? { tone_intensity: action.tone_intensity } : {}),
    }, action.beat_type);
  }

  // ── Story switching ────────────────────────────────────────────────────────

  function switchStory(id: string) {
    if (id === currentStoryId) return;
    abortAll();
    setCurrentStoryId(id);
    localStorage.setItem(LS_CURRENT, id);
    setRecentIds((prev) => addToRecents(id, prev));
    setChapters([]);
    setCurrentChapter(null);
    setPromptInput('');
    setError('');
    setGenStatus('idle');
    setStoryState(null);
    setConfirmAction(null);
    void fetchChapters(id);
    void fetchStoryState(id);
  }

  function newStory() {
    const id = makeStoryId();
    abortAll();
    setCurrentStoryId(id);
    localStorage.setItem(LS_CURRENT, id);
    setRecentIds((prev) => addToRecents(id, prev));
    setChapters([]);
    setCurrentChapter(null);
    setPromptInput('');
    setError('');
    setGenStatus('idle');
    setStoryState(null);
    setConfirmAction(null);
    void fetchStoryState(id);
  }

  // ── Protagonist fetch — creation view only ────────────────────────────────

  useEffect(() => {
    const firstCharId = storyRecord?.character_ids?.[0];
    if (!firstCharId || chapters.length > 0 || isLoadingChapters) return;
    apiClient.getCharacter(firstCharId)
      .then((char) => setProtagonist(char))
      .catch(() => { /* protagonist chip is optional */ });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storyRecord?.character_ids?.[0], chapters.length, isLoadingChapters]);

  // ── Support character helpers ──────────────────────────────────────────────

  function addSupportChar() {
    if (!newSupportName.trim()) return;
    setSupportChars((prev) => [
      ...prev,
      {
        id: `sc-${Date.now()}`,
        name: newSupportName.trim(),
        age: newSupportAge.trim(),
        personality: newSupportPersonality.trim(),
      },
    ]);
    setNewSupportName('');
    setNewSupportAge('');
    setNewSupportPersonality('');
  }

  function buildEffectivePrompt(base: string, chars: SupportChar[]): string {
    if (chars.length === 0) return base;
    const charLines = chars
      .map((c) => `- ${c.name}${c.age ? `, ${c.age}` : ''}${c.personality ? `: ${c.personality}` : ''}`)
      .join('\n');
    return base
      ? `${base}\n\nSupporting characters:\n${charLines}`
      : `Supporting characters:\n${charLines}`;
  }

  // ── On mount ───────────────────────────────────────────────────────────────

  useEffect(() => {
    abortRef.current = new AbortController();
    setRecentIds((prev) => addToRecents(currentStoryId, prev));
    void fetchChapters(currentStoryId);
    void fetchStoryState(currentStoryId);
    return () => {
      abortRef.current?.abort();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Derived ────────────────────────────────────────────────────────────────

  const displayedRecents = recentIds.includes(currentStoryId)
    ? recentIds
    : [currentStoryId, ...recentIds];

  const suggestions: string[] = currentChapter?.suggestions ?? [];

  const clamp = (v: number | string | undefined) =>
    Math.min(1, Math.max(0, typeof v === 'number' ? v : 0));

  // ── Render ─────────────────────────────────────────────────────────────────


  return (
    <div className="flex flex-col min-h-0 flex-1">

      {/* ── Top bar — thin, minimal ────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-4 md:px-5 py-1.5 border-b border-gray-800/40 bg-gray-950/20 flex-wrap">

        {/* Story selector — legacy mode only */}
        {!externalStoryId && (
          <>
            <select
              value={currentStoryId}
              onChange={(e) => switchStory(e.target.value)}
              className="max-w-[160px] h-6 px-1.5 text-[11px] rounded-md bg-transparent border border-gray-800/50 text-gray-600 focus:outline-none focus:border-gray-700 transition"
            >
              {displayedRecents.map((id) => (
                <option key={id} value={id}>{formatStoryId(id)}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={newStory}
              className="h-6 px-2 text-[11px] rounded-md border border-gray-800/40 bg-transparent hover:bg-gray-800/30 text-gray-600 hover:text-gray-400 transition shrink-0"
            >
              + New
            </button>
            <div className="w-px h-3.5 bg-gray-800/40 mx-0.5 shrink-0" />
          </>
        )}

        {/* Story title — named story mode */}
        {externalStoryId && storyTitle && (
          <>
            <span className="text-[11px] text-gray-600 truncate max-w-[160px]">{storyTitle}</span>
            <div className="w-px h-3.5 bg-gray-800/40 mx-0.5 shrink-0" />
          </>
        )}

        {/* Chapter pills */}
        {chapters.length > 0 && (
          <div className="flex items-center gap-1">
            {chapters.map((c) => (
              <button
                key={c.chapter_number}
                type="button"
                onClick={() => void loadChapter(currentStoryId, c.chapter_number)}
                className={`h-6 px-2.5 text-[11px] rounded-md transition ${
                  currentChapter?.chapter_number === c.chapter_number
                    ? 'bg-gray-800/60 text-gray-200 font-medium'
                    : 'text-gray-600 hover:text-gray-400 hover:bg-gray-800/30'
                }`}
              >
                {c.chapter_number}
              </button>
            ))}
          </div>
        )}

        {/* Right-side controls: mode pills + surface toggle */}
        <div className="flex items-center gap-2 ml-auto">
          {/* Mode pills — hidden during creation */}
          {(chapters.length > 0 || isLoadingChapters) && (
            <div className="flex items-center gap-0.5">
              {(['roleplay', 'duet', 'play'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={`h-6 px-2.5 text-[11px] rounded-md capitalize transition ${
                    mode === m
                      ? 'bg-gray-800/60 text-gray-200 font-medium'
                      : 'text-gray-600 hover:text-gray-400 hover:bg-gray-800/30'
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          )}
          {/* Surface mode toggle — Night / Paper */}
          <div className="flex items-center rounded-md border border-gray-800/50 overflow-hidden text-[11px]">
            <button
              type="button"
              onClick={() => setSurfaceMode('night')}
              className={`px-2 h-6 transition ${surfaceMode === 'night' ? 'bg-gray-800/60 text-gray-200' : 'text-gray-600 hover:text-gray-400'}`}
            >Night</button>
            <button
              type="button"
              onClick={() => setSurfaceMode('paper')}
              className={`px-2 h-6 transition ${surfaceMode === 'paper' ? 'bg-[#E8E0D0] text-[#1C1917]' : 'text-gray-600 hover:text-gray-400'}`}
            >Paper</button>
          </div>
        </div>
      </div>

      {/* ── Body — creation view OR reading + right panel ──────────────── */}
      {chapters.length === 0 && !isLoadingChapters && !isGenerating ? (

        /* ── Creation view ───────────────────────────────────────────────── */
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-[560px] mx-auto px-6 py-12">

            {/* Story context */}
            {storyRecord && (
              <div className="mb-6">
                <h2 className="text-xl font-semibold text-gray-100 leading-tight">{storyRecord.title}</h2>
                {(storyRecord.genre || protagonist) && (
                  <div className="flex items-center gap-1.5 mt-1.5 text-[11px] text-gray-500">
                    {storyRecord.genre && <span className="capitalize">{storyRecord.genre}</span>}
                    {storyRecord.genre && protagonist && <span>·</span>}
                    {protagonist && (
                      <span className="flex items-center gap-1">
                        {protagonist.avatar_url ? (
                          <img src={protagonist.avatar_url} alt={protagonist.name} className="w-4 h-4 rounded-full object-cover shrink-0" />
                        ) : (
                          <span className="w-4 h-4 rounded-full bg-gray-800/60 shrink-0 flex items-center justify-center text-[8px] text-gray-500 font-medium">{protagonist.name[0]}</span>
                        )}
                        {protagonist.name}
                      </span>
                    )}
                  </div>
                )}
                {storyRecord.premise && (
                  <p className="text-[13px] text-gray-500 mt-2.5 leading-relaxed">{storyRecord.premise}</p>
                )}
              </div>
            )}

            {/* Protagonist fallback — only when no storyRecord */}
            {!storyRecord && protagonist && (
              <div className="flex items-center gap-2.5 mb-6">
                {protagonist.avatar_url ? (
                  <img
                    src={protagonist.avatar_url}
                    alt={protagonist.name}
                    className="w-8 h-8 rounded-full object-cover shrink-0"
                  />
                ) : (
                  <div className="w-8 h-8 rounded-full bg-gray-800/60 shrink-0 flex items-center justify-center text-[12px] text-gray-500 font-medium">
                    {protagonist.name[0]}
                  </div>
                )}
                <div className="min-w-0">
                  <p className="text-[13px] font-medium text-gray-200 leading-tight truncate">{protagonist.name}</p>
                  <p className="text-[11px] text-gray-500 leading-tight truncate">{protagonist.role || 'Protagonist'}</p>
                </div>
              </div>
            )}

            {/* Opening scene input */}
            <div className="mt-6">
              <textarea
                value={promptInput}
                onChange={(e) => setPromptInput(e.target.value)}
                placeholder="Describe the opening moment — where are they, what's happening, what's the mood?"
                rows={7}
                autoFocus
                className={`w-full resize-none rounded-2xl p-4 text-[14px] focus:outline-none transition leading-relaxed ${
                  surfaceMode === 'paper'
                    ? 'bg-[#F5F0E8] border border-[#A09382]/30 text-[#1C1917] placeholder-[#9D8E7D] focus:border-[#A09382]/60'
                    : 'bg-gray-900/50 border border-gray-700/40 text-gray-200 placeholder-gray-600 focus:border-gray-600/60'
                }`}
              />
            </div>

            {/* Support characters — collapsible */}
            <details className="group mt-5">
              <summary className="text-[10px] font-medium text-gray-600 uppercase tracking-widest cursor-pointer list-none flex items-center gap-1.5 select-none">
                <span className="inline-block text-gray-700 transition-transform duration-150 group-open:rotate-90">{'\u203A'}</span>
                Supporting characters{supportChars.length > 0 && <span className="text-gray-700 normal-case tracking-normal">({supportChars.length})</span>}
              </summary>
              <div className="mt-3 space-y-3">
                {supportChars.length > 0 && (
                  <ul className="space-y-1.5">
                    {supportChars.map((c) => (
                      <li key={c.id} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-900/20">
                        <span className="text-[12px] text-gray-300 flex-1 truncate">
                          {c.name}{c.age ? `, ${c.age}` : ''}{c.personality ? ` — ${c.personality}` : ''}
                        </span>
                        <button
                          type="button"
                          onClick={() => setSupportChars((p) => p.filter((x) => x.id !== c.id))}
                          className="text-[11px] text-gray-700 hover:text-red-400 transition shrink-0"
                        >
                          ✕
                        </button>
                      </li>
                    ))}
                  </ul>
                )}

                <div className="space-y-1.5">
                  <div className="flex gap-1.5">
                    <input
                      type="text"
                      value={newSupportName}
                      onChange={(e) => setNewSupportName(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addSupportChar(); } }}
                      placeholder="Name"
                      className="flex-1 min-w-[100px] h-8 px-2.5 text-[12px] rounded-lg bg-gray-900/30 border border-gray-800/50 text-gray-300 placeholder-gray-700 focus:outline-none focus:border-gray-700 transition"
                    />
                    <input
                      type="text"
                      value={newSupportAge}
                      onChange={(e) => setNewSupportAge(e.target.value)}
                      placeholder="Age"
                      className="w-14 h-8 px-2.5 text-[12px] rounded-lg bg-gray-900/30 border border-gray-800/50 text-gray-300 placeholder-gray-700 focus:outline-none focus:border-gray-700 transition"
                    />
                  </div>
                  <div className="flex gap-1.5">
                    <input
                      type="text"
                      value={newSupportPersonality}
                      onChange={(e) => setNewSupportPersonality(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addSupportChar(); } }}
                      placeholder="Personality / role"
                      className="flex-1 min-w-[140px] h-8 px-2.5 text-[12px] rounded-lg bg-gray-900/30 border border-gray-800/50 text-gray-300 placeholder-gray-700 focus:outline-none focus:border-gray-700 transition"
                    />
                    <button
                      type="button"
                      onClick={addSupportChar}
                      disabled={!newSupportName.trim()}
                      className="h-8 px-3 text-[12px] rounded-lg border border-gray-700/50 text-gray-400 hover:text-gray-200 hover:border-gray-600 transition disabled:opacity-30 disabled:cursor-not-allowed shrink-0"
                    >
                      + Add
                    </button>
                  </div>
                </div>
              </div>
            </details>

            {/* Generation settings — collapsible */}
            <details className="group mt-4">
              <summary className="text-[10px] font-medium text-gray-600 uppercase tracking-widest cursor-pointer list-none flex items-center gap-1.5 select-none">
                <span className="inline-block text-gray-700 transition-transform duration-150 group-open:rotate-90">{'\u203A'}</span>
                Generation settings
              </summary>
              <div className="mt-4 space-y-4">
                <div className="space-y-2">
                  <p className="text-[10px] text-gray-700 tracking-wider">Direction</p>
                  <div className="flex flex-wrap gap-1.5">
                    {[
                      { value: 'advance_plot',     label: 'Advance' },
                      { value: 'quiet_reflection', label: 'Reflective' },
                      { value: 'argument_begins',  label: 'Tension' },
                      { value: 'add_dialogue',     label: 'Dialogue' },
                      { value: 'twist_event',      label: 'Twist' },
                      { value: 'romantic_moment',  label: 'Romantic' },
                    ].map(({ value, label }) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setSlControls((p) => ({ ...p, direction: value }))}
                        className={`text-[11px] px-2.5 py-1 rounded-md border transition ${
                          slControls.direction === value
                            ? 'bg-emerald-600/30 border-emerald-500/50 text-emerald-300'
                            : 'border-gray-800/40 text-gray-500 hover:border-gray-700 hover:text-gray-400'
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {[
                    { label: 'Tone', key: 'tone_intensity' as const, options: ['light', 'moderate', 'intense'] },
                    { label: 'Pacing', key: 'pacing' as const, options: ['slow', 'balanced', 'fast'] },
                    { label: 'Length', key: 'length' as const, options: ['short', 'medium', 'long'] },
                    { label: 'Boundary', key: 'boundary' as const, options: ['sfw', 'fade_to_black', 'sensual'] },
                  ].map(({ label, key, options }) => (
                    <div key={key} className="space-y-1">
                      <p className="text-[10px] text-gray-700 tracking-wider">{label}</p>
                      <select
                        value={slControls[key]}
                        onChange={(e) => setSlControls((p) => ({ ...p, [key]: e.target.value }))}
                        className="w-full h-7 px-1.5 text-[11px] rounded-md bg-gray-900/30 border border-gray-800/50 text-gray-400 focus:outline-none focus:border-gray-700 transition capitalize"
                      >
                        {options.map((o) => (
                          <option key={o} value={o}>{o.replace('_', ' ')}</option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              </div>
            </details>

            {/* CTA */}
            <div className="mt-8">
              {genStatus === 'failed' && error && (
                <p className="text-[12px] text-red-400 mb-3">{error}</p>
              )}
              <button
                type="button"
                onClick={() => void handleGenerate()}
                disabled={isGenerating}
                className="w-full py-4 rounded-2xl bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white font-semibold text-[15px] tracking-wide shadow-[0_4px_24px_rgba(16,185,129,0.18)] transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Write Opening Chapter →
              </button>
            </div>

          </div>
        </div>

      ) : (

      /* ── Body — reading column + right panel ────────────────────────── */
      <div className="flex flex-col md:flex-row min-h-0 flex-1">

        {/* ── Reading column ────────────────────────────────────────────── */}
        <div className={`flex-1 min-h-0 overflow-y-auto transition-colors duration-200 ${surfaceMode === 'paper' ? 'bg-[#F5F0E8] shadow-[0_8px_30px_rgba(0,0,0,0.05)]' : ''}`}>
          <div className="max-w-[720px] mx-auto px-6 md:px-12 py-12 prose-p:my-5">

            {/* Chapter header */}
            {currentChapter ? (
              <div className="mb-8">
                <div className="flex items-baseline justify-between">
                  <span className={`text-[12px] font-semibold uppercase tracking-[0.14em] transition-colors duration-200 ${surfaceMode === 'paper' ? 'text-[#7A6E5F]' : 'text-gray-500'}`}>
                    Chapter {currentChapter.chapter_number}
                  </span>
                  <span className={`text-[11px] transition-colors duration-200 ${surfaceMode === 'paper' ? 'text-[#9D8E7D]' : 'text-gray-700'}`}>{currentChapter.words} words</span>
                </div>

                {/* Prompt reveal */}
                {currentChapter.prompt_text && (
                  <div className="mt-2">
                    <button
                      type="button"
                      onClick={() => setPromptRevealOpen((p) => !p)}
                      className="flex items-center gap-1.5 text-[11px] text-gray-700 hover:text-gray-500 transition"
                    >
                      <span className={`transition-transform duration-150 text-[10px] ${promptRevealOpen ? 'rotate-90' : ''}`}>{'\u203A'}</span>
                      Prompt
                    </button>
                    {promptRevealOpen && (
                      <p className="mt-1.5 pl-3 text-[11px] text-gray-600 leading-relaxed border-l border-gray-800/40">
                        {currentChapter.prompt_text}
                      </p>
                    )}
                  </div>
                )}
              </div>
            ) : isLoadingChapters ? (
              <div className="mb-8">
                <div className="h-3 w-24 bg-gray-800/60 rounded-full animate-pulse" />
              </div>
            ) : null}

            {/* Chapter text / empty / generating states */}
            {isGenerating ? (
              <div className="py-16">
                <div className="space-y-5 max-w-[480px] mx-auto">
                  {[92, 100, 88, 100, 72, 100, 96, 100, 64, 100, 84, 100].map((w, i) => (
                    <div
                      key={i}
                      className="h-[2px] bg-gray-800 rounded-full animate-pulse"
                      style={{ width: `${w}%`, animationDelay: `${i * 80}ms` }}
                    />
                  ))}
                </div>
                <p className="text-center text-[12px] text-gray-600 tracking-wide mt-10">Writing chapter{'\u2026'}</p>
              </div>
            ) : isLoadingChapter ? (
              <div className="py-16">
                <div className="space-y-5 max-w-[480px] mx-auto">
                  {[100, 88, 100, 72, 96, 100].map((w, i) => (
                    <div
                      key={i}
                      className="h-[2px] bg-gray-800 rounded-full animate-pulse"
                      style={{ width: `${w}%`, animationDelay: `${i * 80}ms` }}
                    />
                  ))}
                </div>
              </div>
            ) : currentChapter ? (
              <p className={`text-[16px] leading-[1.9] whitespace-pre-wrap font-normal tracking-[0.01em] transition-colors duration-200 animate-[fadeIn_0.25s_ease] ${surfaceMode === 'paper' ? 'text-[#1C1917]' : 'text-gray-100'}`}>
                {currentChapter.generated_text}
              </p>
            ) : (
              <div className="py-24 text-center">
                <p className="text-gray-700 text-sm">No chapters yet</p>
                <p className="text-gray-800 text-[12px] mt-2 leading-relaxed max-w-[320px] mx-auto">
                  Add guidance on the right, then generate your opening chapter.
                </p>
              </div>
            )}

            {/* ── Beat System / CTA — below text ─────────────────────────── */}
            {!isLoadingChapters && (
              <div className="mt-16 pt-10 border-t border-gray-700/20 space-y-4">

                {chapters.length > 0 ? (
                  <>
                    {/* Beat bar label */}
                    <p className="text-[10px] font-medium text-gray-600 uppercase tracking-widest">
                      What happens next?
                    </p>

                    {/* Beat action grid — 2 cols on mobile, 3 on sm+ */}
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                      {BEAT_ACTIONS.map((action) => (
                        <button
                          key={action.label}
                          type="button"
                          onClick={() => handleBeatAction(action)}
                          disabled={isGenerating}
                          className="group flex flex-col gap-0.5 px-3 py-2.5 rounded-xl border border-gray-800/50 bg-gray-900/20 hover:border-emerald-700/40 hover:bg-emerald-950/20 active:bg-emerald-950/30 transition text-left disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          <span className="text-[13px] font-medium text-gray-300 group-hover:text-emerald-300 transition leading-tight">
                            {action.label}
                          </span>
                          <span className="text-[11px] text-gray-600 leading-snug">
                            {action.hint}
                          </span>
                        </button>
                      ))}
                    </div>

                    {/* Full chapter — secondary option */}
                    <div className="flex items-center justify-between pt-1">
                      <button
                        type="button"
                        onClick={() => void handleGenerate()}
                        disabled={isGenerating}
                        className="text-[12px] text-gray-600 hover:text-gray-400 transition disabled:opacity-40"
                      >
                        {isGenerating ? 'Writing\u2026' : 'Write full chapter \u2192'}
                      </button>
                    </div>
                  </>
                ) : (
                  /* Opening — no chapters yet */
                  <button
                    type="button"
                    onClick={() => void handleGenerate()}
                    disabled={isGenerating}
                    className="w-full py-3 rounded-2xl bg-emerald-700/80 hover:bg-emerald-600 active:bg-emerald-700 text-white font-semibold text-sm tracking-wide shadow-[0_4px_20px_rgba(16,185,129,0.10)] transition disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isGenerating ? 'Writing\u2026' : 'Write Opening Chapter'}
                  </button>
                )}

                {/* Error state — inline */}
                {genStatus === 'failed' && error ? (
                  <div className="flex items-start gap-2">
                    <p className="text-[12px] text-red-400 leading-relaxed flex-1">{error}</p>
                    <button
                      type="button"
                      onClick={() => void handleGenerate()}
                      disabled={isGenerating}
                      className="shrink-0 px-3 py-1 rounded-lg text-[11px] text-red-400 border border-red-800/40 hover:bg-red-900/20 transition disabled:opacity-50"
                    >
                      Retry
                    </button>
                  </div>
                ) : error ? (
                  <p className="text-[12px] text-red-400">{error}</p>
                ) : null}

              </div>
            )}

            {/* Delete / Regenerate — small, secondary */}
            {currentChapter && !isGenerating && (
              <div className="mt-4 flex items-center gap-2">
                {confirmAction === 'delete' ? (
                  <>
                    <span className="text-[11px] text-gray-600 self-center">Delete this chapter?</span>
                    <button
                      type="button"
                      onClick={() => void handleDelete()}
                      className="px-2.5 py-0.5 text-[11px] rounded-md bg-red-700/30 hover:bg-red-600/40 border border-red-700/40 text-red-400 transition"
                    >
                      Confirm
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmAction(null)}
                      className="px-2.5 py-0.5 text-[11px] rounded-md border border-gray-800/40 text-gray-600 hover:text-gray-400 transition"
                    >
                      Cancel
                    </button>
                  </>
                ) : confirmAction === 'regenerate' ? (
                  <>
                    <span className="text-[11px] text-gray-600 self-center">Replace with new generation?</span>
                    <button
                      type="button"
                      onClick={() => void handleRegenerate()}
                      className="px-2.5 py-0.5 text-[11px] rounded-md bg-amber-700/30 hover:bg-amber-600/40 border border-amber-700/40 text-amber-400 transition"
                    >
                      Confirm
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmAction(null)}
                      className="px-2.5 py-0.5 text-[11px] rounded-md border border-gray-800/40 text-gray-600 hover:text-gray-400 transition"
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => setConfirmAction('delete')}
                      className="px-2.5 py-0.5 text-[11px] rounded-md text-gray-700 hover:text-red-400 transition"
                    >
                      Delete chapter
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmAction('regenerate')}
                      className="px-2.5 py-0.5 text-[11px] rounded-md text-gray-700 hover:text-amber-400 transition"
                    >
                      Regenerate
                    </button>
                  </>
                )}
              </div>
            )}

          </div>
        </div>

        {/* ── Right panel — guidance controls ──────────────────────────── */}
        <div className="w-full md:w-[260px] shrink-0 border-t md:border-t-0 md:border-l border-gray-800/40 overflow-y-auto px-4 py-5 space-y-5">

          {/* Suggestions */}
          {suggestions.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] font-medium text-gray-600 uppercase tracking-widest">Suggestions</p>
              <ul className="space-y-1.5">
                {suggestions.map((s, i) => (
                  <li key={i}>
                    <button
                      type="button"
                      onClick={() => setPromptInput(s)}
                      className="text-left w-full flex gap-2 text-[12px] text-gray-400 hover:text-emerald-300 leading-relaxed transition group"
                    >
                      <span className="mt-0.5 shrink-0 text-emerald-700 group-hover:text-emerald-400 transition">{'\u203A'}</span>
                      <span>{s}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Guidance */}
          <div className="space-y-1.5">
            <p className="text-[10px] font-medium text-gray-600 uppercase tracking-widest">Guidance</p>
            <textarea
              value={promptInput}
              onChange={(e) => setPromptInput(e.target.value)}
              placeholder="A beat, dialogue, rough notes..."
              rows={3}
              className="w-full resize-none rounded-lg bg-gray-900/30 border border-gray-800/50 p-2.5 text-[12px] text-gray-300 placeholder-gray-700 focus:outline-none focus:border-gray-700 transition leading-relaxed"
            />
          </div>

          {/* Direction chips */}
          <div className="space-y-2">
            <p className="text-[10px] font-medium text-gray-600 uppercase tracking-widest">Direction</p>
            {(
              [
                { group: 'Emotion',    chips: [{ value: 'sad_moment', label: 'Sad' }, { value: 'quiet_reflection', label: 'Reflective' }] },
                { group: 'Conflict',   chips: [{ value: 'argument_begins', label: 'Argument' }, { value: 'twist_event', label: 'Twist' }] },
                { group: 'Movement',   chips: [{ value: 'advance_plot', label: 'Advance' }, { value: 'action_sequence', label: 'Action' }, { value: 'add_dialogue', label: 'Dialogue' }] },
                { group: 'Connection', chips: [{ value: 'romantic_moment', label: 'Romantic' }, { value: 'sensual_scene', label: 'Sensual' }, { value: 'intimate_scene', label: 'Intimate' }] },
              ] as { group: string; chips: { value: string; label: string }[] }[]
            ).map(({ group, chips }) => (
              <div key={group} className="space-y-1">
                <p className="text-[10px] text-gray-700 tracking-wider">{group}</p>
                <div className="flex flex-wrap gap-1">
                  {chips.map(({ value, label }) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setSlControls((p) => ({ ...p, direction: value }))}
                      className={`text-[11px] px-2 py-0.5 rounded-md border transition ${
                        slControls.direction === value
                          ? 'bg-emerald-600/30 border-emerald-500/50 text-emerald-300'
                          : 'border-gray-800/40 text-gray-500 hover:border-gray-700 hover:text-gray-400'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* Tone + Pacing — two columns */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <p className="text-[10px] font-medium text-gray-600 uppercase tracking-widest">Tone</p>
              <div className="flex flex-col gap-1">
                {(['light','moderate','intense'] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setSlControls((p) => ({ ...p, tone_intensity: v }))}
                    className={`py-1 text-[11px] rounded-md border transition capitalize ${
                      slControls.tone_intensity === v
                        ? 'bg-emerald-600/30 border-emerald-500/50 text-emerald-300'
                        : 'border-gray-800/40 text-gray-500 hover:border-gray-700 hover:text-gray-400'
                    }`}
                  >
                    {v}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-1.5">
              <p className="text-[10px] font-medium text-gray-600 uppercase tracking-widest">Pacing</p>
              <div className="flex flex-col gap-1">
                {(['slow','balanced','fast'] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setSlControls((p) => ({ ...p, pacing: v }))}
                    className={`py-1 text-[11px] rounded-md border transition capitalize ${
                      slControls.pacing === v
                        ? 'bg-emerald-600/30 border-emerald-500/50 text-emerald-300'
                        : 'border-gray-800/40 text-gray-500 hover:border-gray-700 hover:text-gray-400'
                    }`}
                  >
                    {v}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Boundary + Length — two columns */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <p className="text-[10px] font-medium text-gray-600 uppercase tracking-widest">Boundary</p>
              <select
                value={slControls.boundary}
                onChange={(e) => setSlControls((p) => ({ ...p, boundary: e.target.value }))}
                className="w-full h-7 px-1.5 text-[11px] rounded-md bg-gray-900/30 border border-gray-800/50 text-gray-400 focus:outline-none focus:border-gray-700 transition"
              >
                <option value="sfw">SFW</option>
                <option value="fade_to_black">Fade to black</option>
                <option value="sensual">Sensual</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <p className="text-[10px] font-medium text-gray-600 uppercase tracking-widest">Length</p>
              <select
                value={slControls.length}
                onChange={(e) => setSlControls((p) => ({ ...p, length: e.target.value }))}
                className="w-full h-7 px-1.5 text-[11px] rounded-md bg-gray-900/30 border border-gray-800/50 text-gray-400 focus:outline-none focus:border-gray-700 transition"
              >
                <option value="short">Short</option>
                <option value="medium">Medium</option>
                <option value="long">Long</option>
              </select>
            </div>
          </div>

          {/* Story state bars — compact, at bottom */}
          <div className="space-y-2 pt-2">
            <div className="flex items-center justify-between">
              <p className="text-[10px] font-medium text-gray-600 uppercase tracking-widest">Story State</p>
              {isLoadingState && <span className="text-[10px] text-gray-700">{'\u2026'}</span>}
            </div>
            {storyState ? (
              <div className="space-y-2">
                {(
                  [
                    { label: 'Emotion',  value: clamp(storyState.emotional_weight) },
                    { label: 'Tension',  value: clamp(storyState.tension) },
                    { label: 'Stakes',   value: clamp(storyState.stakes) },
                    { label: 'Intimacy', value: clamp(storyState.intimacy_level), dim: slControls.boundary === 'sfw' },
                  ] as { label: string; value: number; dim?: boolean }[]
                ).map(({ label, value, dim }) => (
                  <div key={label} className={dim ? 'opacity-30' : undefined}>
                    <div className="flex justify-between mb-0.5">
                      <span className="text-[10px] text-gray-600">{label}</span>
                      <span className="text-[10px] text-gray-700">{Math.round(value * 100)}%</span>
                    </div>
                    <div className="h-0.5 bg-gray-800/60 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-emerald-700/50 rounded-full transition-[width] duration-500 ease-out"
                        style={{ width: `${value * 100}%` }}
                      />
                    </div>
                  </div>
                ))}
                <div className="pt-1.5 border-t border-gray-800/30 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px]">
                  <span className="text-gray-700">Tone</span>
                  <span className="text-gray-500">{storyState.tone}</span>
                  <span className="text-gray-700">Pacing</span>
                  <span className="text-gray-500">{storyState.pacing}</span>
                </div>
              </div>
            ) : (
              <p className="text-[11px] text-gray-700">
                {isLoadingState ? 'Loading\u2026' : 'No state yet.'}
              </p>
            )}
          </div>

        </div>
      </div>
      )}

    </div>
  );
}
