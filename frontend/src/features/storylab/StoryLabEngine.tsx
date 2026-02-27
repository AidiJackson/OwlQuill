/**
 * StoryLabEngine — RedQuill-parity chapter-based writing panel.
 *
 * Each generation produces a NEW CHAPTER (fresh output), stored in the backend.
 * After generation, 3 continuation suggestions + a manual prompt box are shown.
 * Chapters are listed in a left sidebar (desktop) or dropdown (mobile).
 *
 * Story IDs are per-session strings stored in localStorage (unchanged).
 */
import { useState, useEffect, useRef, useCallback } from 'react';

// ── localStorage keys ─────────────────────────────────────────────────────────

const LS_CURRENT = 'ficshon_storylab_current_story_id';
const LS_RECENTS = 'ficshon_storylab_recent_story_ids';

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

// ── Direction chip data ───────────────────────────────────────────────────────

const DIRECTION_GROUPS: { group: string; chips: { value: string; label: string }[] }[] = [
  { group: 'Emotion',    chips: [{ value: 'sad_moment', label: 'Sad' }, { value: 'quiet_reflection', label: 'Reflective' }] },
  { group: 'Conflict',   chips: [{ value: 'argument_begins', label: 'Argument' }, { value: 'twist_event', label: 'Twist' }] },
  { group: 'Movement',   chips: [{ value: 'advance_plot', label: 'Advance Plot' }, { value: 'action_sequence', label: 'Action' }, { value: 'add_dialogue', label: 'Dialogue' }] },
  { group: 'Connection', chips: [{ value: 'romantic_moment', label: 'Romantic' }, { value: 'sensual_scene', label: 'Sensual' }, { value: 'intimate_scene', label: 'Intimate' }] },
];

// ── Component ─────────────────────────────────────────────────────────────────

export default function StoryLabEngine() {
  // ── Story-ID state ─────────────────────────────────────────────────────────

  const [currentStoryId, setCurrentStoryId] = useState<string>(() => {
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

  // ── UI state ───────────────────────────────────────────────────────────────

  const [promptRevealOpen, setPromptRevealOpen] = useState(false);
  const [confirmAction, setConfirmAction] = useState<'delete' | 'regenerate' | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // Story progress state (from /state endpoint)
  const [storyState, setStoryState] = useState<SLStoryState | null>(null);
  const [isLoadingState, setIsLoadingState] = useState(false);

  const abortRef = useRef<AbortController | null>(null);

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
      const resp = await fetch(
        `/api/storylab/chapters?story_id=${encodeURIComponent(storyId)}`,
        { signal: abortRef.current?.signal },
      );
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
      const resp = await fetch(
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
      const resp = await fetch(
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

  async function handleGenerate() {
    setError('');
    setConfirmAction(null);
    setIsGenerating(true);
    try {
      const payload = {
        prompt: promptInput,
        mode,
        controls: slControls,
      };
      const resp = await fetch(
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
      const newChapter: ChapterDetail = {
        chapter_number: data.chapter_number,
        generated_text: data.generated_text,
        prompt_text: data.prompt_text,
        controls: slControls,
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
            boundary: slControls.boundary,
            length: slControls.length,
          },
        ].sort((a, b) => a.chapter_number - b.chapter_number);
      });
      setPromptInput('');
      // Refresh state for progress bars
      void fetchStoryState(currentStoryId);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      setError((err as Error).message || 'Generation failed.');
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleDelete() {
    if (!currentChapter) return;
    setConfirmAction(null);
    try {
      const resp = await fetch(
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
    setIsGenerating(true);
    setError('');
    try {
      const payload = {
        prompt: currentChapter.prompt_text,
        mode,
        controls: slControls,
      };
      const resp = await fetch(
        `/api/storylab/chapters/${currentChapter.chapter_number}/regenerate?story_id=${encodeURIComponent(currentStoryId)}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          signal: abortRef.current?.signal,
        },
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data = await resp.json() as any;
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
      void fetchStoryState(currentStoryId);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      setError('Regenerate failed.');
    } finally {
      setIsGenerating(false);
    }
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
    setStoryState(null);
    setConfirmAction(null);
    void fetchStoryState(id);
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

      {/* ── Top management bar (simplified) ──────────────────────────────── */}
      <div className="flex items-center gap-2 px-4 md:px-5 py-2 border-b border-gray-800/60 bg-gray-950/40">

        {/* Story selector */}
        <span className="text-[10px] text-gray-600 uppercase tracking-wider font-medium shrink-0">Story</span>
        <select
          value={currentStoryId}
          onChange={(e) => switchStory(e.target.value)}
          className="flex-1 max-w-[200px] h-7 px-2 text-xs rounded-lg bg-gray-900/60 border border-gray-800 text-gray-300 focus:outline-none focus:border-emerald-700/50 focus:ring-1 focus:ring-emerald-900/30 transition"
        >
          {displayedRecents.map((id) => (
            <option key={id} value={id}>{formatStoryId(id)}</option>
          ))}
        </select>

        <button
          type="button"
          onClick={newStory}
          className="h-7 px-3 text-xs rounded-lg border border-gray-700/60 bg-gray-900/40 hover:bg-gray-800/50 hover:border-gray-600 text-gray-400 hover:text-gray-300 transition shrink-0 ml-auto"
        >
          + New story
        </button>
      </div>

      {/* ── Three-column layout ──────────────────────────────────────────── */}
      <div className="flex min-h-0 flex-1">

        {/* ── Left sidebar: chapter list (desktop only) ──────────────────── */}
        <aside className="hidden md:flex flex-col w-44 shrink-0 border-r border-gray-800/60 bg-gray-950/20">

          {/* Sidebar header */}
          <div className="flex items-center justify-between px-3 py-2.5 border-b border-gray-800/40">
            <span className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Chapters</span>
            <button
              type="button"
              onClick={newStory}
              className="text-[10px] text-emerald-500/80 hover:text-emerald-400 font-medium transition"
            >
              + New
            </button>
          </div>

          {/* Chapter list */}
          <nav className="flex-1 overflow-y-auto py-1">
            {isLoadingChapters ? (
              <div className="px-3 py-2 space-y-2.5 animate-pulse">
                <div className="h-2 w-16 bg-gray-800 rounded" />
                <div className="h-2 w-12 bg-gray-800 rounded" />
                <div className="h-2 w-14 bg-gray-800 rounded" />
              </div>
            ) : chapters.length === 0 ? (
              <p className="px-3 py-3 text-[11px] text-gray-600 italic leading-relaxed">
                No chapters yet
              </p>
            ) : (
              chapters.map((c) => {
                const isActive = c.chapter_number === currentChapter?.chapter_number;
                return (
                  <button
                    key={c.chapter_number}
                    type="button"
                    onClick={() => void loadChapter(currentStoryId, c.chapter_number)}
                    className={`w-full text-left px-3 py-2.5 transition-colors ${
                      isActive
                        ? 'bg-emerald-900/30 text-emerald-300 border-l-2 border-emerald-500'
                        : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800/30 border-l-2 border-transparent'
                    }`}
                  >
                    <span className="block text-xs font-medium">Ch {c.chapter_number}</span>
                    <span className="block text-[10px] text-gray-600 mt-0.5">{c.words} w</span>
                  </button>
                );
              })
            )}
          </nav>
        </aside>

        {/* ── Center: reader column ──────────────────────────────────────── */}
        <div className="flex flex-col flex-1 min-h-0 overflow-hidden">

          {/* Mobile-only chapter select */}
          {chapters.length > 0 && (
            <div className="md:hidden px-4 pt-3 pb-1">
              <select
                value={currentChapter?.chapter_number ?? ''}
                onChange={(e) => void loadChapter(currentStoryId, parseInt(e.target.value))}
                className="w-full h-8 px-2.5 text-xs rounded-lg bg-gray-900/60 border border-gray-800 text-gray-300 focus:outline-none focus:border-emerald-700/50 transition"
              >
                {chapters.map((c) => (
                  <option key={c.chapter_number} value={c.chapter_number}>
                    Ch {c.chapter_number} -- {c.words} w
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Chapter header */}
          <div className="px-4 md:px-6 pt-4 pb-2">
            {currentChapter ? (
              <>
                <div className="flex items-center justify-between">
                  <div className="flex items-baseline gap-2">
                    <span className="text-xs font-semibold text-gray-300 tracking-wide">
                      Ch {currentChapter.chapter_number}
                    </span>
                    <span className="text-[10px] text-gray-600 font-medium">
                      {currentChapter.words} words
                    </span>
                  </div>

                  {/* Delete + Regen trigger buttons */}
                  {!isGenerating && (
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => setConfirmAction(confirmAction === 'delete' ? null : 'delete')}
                        className="px-2 py-1 text-[10px] text-gray-600 hover:text-red-400 transition rounded"
                      >
                        Delete
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmAction(confirmAction === 'regenerate' ? null : 'regenerate')}
                        className="px-2 py-1 text-[10px] text-gray-600 hover:text-amber-400 transition rounded"
                      >
                        Regen
                      </button>
                    </div>
                  )}
                </div>

                {/* Prompt reveal */}
                {currentChapter.prompt_text && (
                  <div className="mt-1.5">
                    <button
                      type="button"
                      onClick={() => setPromptRevealOpen((p) => !p)}
                      className="flex items-center gap-1.5 text-[10px] text-gray-600 hover:text-gray-400 transition"
                    >
                      <span className={`inline-block transition-transform duration-200 ${promptRevealOpen ? 'rotate-90' : ''}`}>
                        &#x203A;
                      </span>
                      <span>Prompt for this chapter</span>
                    </button>
                    {promptRevealOpen && (
                      <p className="mt-1.5 pl-3.5 text-[11px] text-gray-500 leading-relaxed border-l border-gray-800/80">
                        {currentChapter.prompt_text}
                      </p>
                    )}
                  </div>
                )}
              </>
            ) : isLoadingChapters ? (
              <div className="h-4 w-32 bg-gray-800 rounded animate-pulse" />
            ) : (
              <>
                <p className="text-xs font-semibold text-gray-400 tracking-wide">No chapters yet</p>
                <p className="text-[11px] text-gray-600 mt-1 leading-relaxed">
                  Write a prompt on the right, then generate your opening chapter.
                </p>
              </>
            )}
          </div>

          {/* Reader pane */}
          <div className="flex-1 min-h-0 px-4 md:px-6 pb-3">
            <div className="h-full overflow-y-auto rounded-xl bg-gray-900/60 border border-gray-800/70 shadow-[0_4px_24px_rgba(0,0,0,0.2)] p-5 md:p-7">
              {isLoadingChapter ? (
                <div className="space-y-3 animate-pulse">
                  {[...Array(7)].map((_, i) => (
                    <div key={i} className={`h-2 bg-gray-800/80 rounded ${i % 4 === 3 ? 'w-3/5' : i % 5 === 2 ? 'w-4/5' : 'w-full'}`} />
                  ))}
                </div>
              ) : currentChapter ? (
                <p className="text-[15px] leading-[1.85] text-gray-100 whitespace-pre-wrap tracking-[0.01em]">
                  {currentChapter.generated_text}
                </p>
              ) : (
                <p className="text-gray-700 text-sm italic">Your chapter will appear here.</p>
              )}
            </div>
          </div>

          {/* Confirm action bar (inline below reader) */}
          {currentChapter && confirmAction && !isGenerating && (
            <div className="px-4 md:px-6 pb-3">
              <div className="flex items-center gap-2">
                {confirmAction === 'delete' ? (
                  <>
                    <span className="text-xs text-gray-500">Delete this chapter?</span>
                    <button
                      type="button"
                      onClick={() => void handleDelete()}
                      className="px-3 py-1 text-xs rounded-lg bg-red-700/40 hover:bg-red-600/50 border border-red-700/60 text-red-300 transition"
                    >
                      Confirm delete
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmAction(null)}
                      className="px-3 py-1 text-xs rounded-lg border border-gray-700/60 bg-gray-900/40 text-gray-500 hover:text-gray-400 transition"
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <span className="text-xs text-gray-500">Replace with new generation?</span>
                    <button
                      type="button"
                      onClick={() => void handleRegenerate()}
                      className="px-3 py-1 text-xs rounded-lg bg-amber-700/40 hover:bg-amber-600/50 border border-amber-700/60 text-amber-300 transition"
                    >
                      Confirm
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmAction(null)}
                      className="px-3 py-1 text-xs rounded-lg border border-gray-700/60 bg-gray-900/40 text-gray-500 hover:text-gray-400 transition"
                    >
                      Cancel
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
        </div>

        {/* ── Right column: continue panel ───────────────────────────────── */}
        <div className="w-full md:w-[300px] shrink-0 flex flex-col gap-3 overflow-y-auto border-l border-gray-800/60 p-4 md:py-4 md:px-4 bg-gray-950/20">

          {/* Suggestions */}
          {suggestions.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">StoryLab suggests</p>
              <ul className="space-y-1">
                {suggestions.map((s, i) => (
                  <li key={i}>
                    <button
                      type="button"
                      onClick={() => setPromptInput(s)}
                      className="text-left w-full flex gap-2 px-2.5 py-2 text-xs text-gray-400 hover:text-emerald-300 leading-relaxed rounded-lg hover:bg-emerald-900/10 transition group"
                    >
                      <span className="mt-0.5 shrink-0 text-emerald-700 group-hover:text-emerald-400 transition">&#x203A;</span>
                      <span>{s}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Continue card */}
          <div className="rounded-xl border border-gray-800/70 bg-gray-900/40 p-4 space-y-3">
            <p className="text-xs font-semibold text-gray-300 tracking-wide">What happens next?</p>
            <textarea
              value={promptInput}
              onChange={(e) => setPromptInput(e.target.value)}
              placeholder="Write a beat, a line of dialogue, or paste rough notes..."
              rows={4}
              className="w-full resize-none rounded-lg bg-gray-950/60 border border-gray-800/70 p-3 text-sm text-gray-200 placeholder-gray-700 focus:outline-none focus:border-emerald-800/50 focus:ring-1 focus:ring-emerald-900/30 transition leading-relaxed"
            />
            <button
              type="button"
              onClick={() => void handleGenerate()}
              disabled={isGenerating}
              className="w-full py-2.5 px-4 rounded-lg bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white font-semibold text-sm transition disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {isGenerating
                ? 'Generating\u2026'
                : chapters.length === 0
                  ? 'Generate Opening Chapter'
                  : 'Continue \u2014 New Chapter'}
            </button>
          </div>

          {/* Error */}
          {error && (
            <p className="text-xs text-red-400 px-0.5">{error}</p>
          )}

          {/* ── Advanced collapsible ─────────────────────────────────────── */}
          <div className="rounded-xl border border-gray-800/50 overflow-hidden">

            {/* Advanced header */}
            <button
              type="button"
              onClick={() => setAdvancedOpen((p) => !p)}
              className="w-full flex items-center justify-between px-4 py-2.5 text-xs text-gray-500 hover:text-gray-400 transition"
            >
              <span className="font-medium tracking-wide">Advanced</span>
              <span className={`inline-block transition-transform duration-200 text-sm ${advancedOpen ? 'rotate-90' : ''}`}>
                &#x203A;
              </span>
            </button>

            {/* Advanced body */}
            {advancedOpen && (
              <div className="px-4 pb-4 space-y-4 border-t border-gray-800/40 pt-3">

                {/* Direction chips */}
                <div className="space-y-2">
                  <p className="text-[10px] text-gray-500 font-medium uppercase tracking-wider">Direction</p>
                  {DIRECTION_GROUPS.map(({ group, chips }) => (
                    <div key={group} className="space-y-1">
                      <p className="text-[10px] text-gray-600 uppercase tracking-wider">{group}</p>
                      <div className="flex flex-wrap gap-1.5">
                        {chips.map(({ value, label }) => (
                          <button
                            key={value}
                            type="button"
                            onClick={() => setSlControls((p) => ({ ...p, direction: value }))}
                            className={`px-2.5 py-1 text-[11px] rounded-lg border transition ${
                              slControls.direction === value
                                ? 'bg-emerald-600/30 border-emerald-500/60 text-emerald-300'
                                : 'bg-gray-900/40 border-gray-700/60 text-gray-500 hover:border-gray-600 hover:text-gray-300'
                            }`}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Boundary */}
                <div className="space-y-1">
                  <p className="text-[10px] text-gray-500 font-medium uppercase tracking-wider">Boundary</p>
                  <select
                    value={slControls.boundary}
                    onChange={(e) => setSlControls((p) => ({ ...p, boundary: e.target.value }))}
                    className="w-full h-7 px-2 text-xs rounded-lg bg-gray-900/60 border border-gray-800 text-gray-300 focus:outline-none focus:border-emerald-700/50 transition"
                  >
                    <option value="sfw">SFW</option>
                    <option value="fade_to_black">Fade to black</option>
                    <option value="sensual">Sensual</option>
                  </select>
                </div>

                {/* Tone */}
                <div className="space-y-1">
                  <p className="text-[10px] text-gray-500 font-medium uppercase tracking-wider">Tone</p>
                  <div className="flex gap-1.5">
                    {(['light', 'moderate', 'intense'] as const).map((v) => (
                      <button
                        key={v}
                        type="button"
                        onClick={() => setSlControls((p) => ({ ...p, tone_intensity: v }))}
                        className={`flex-1 py-1.5 text-[11px] rounded-lg border transition capitalize ${
                          slControls.tone_intensity === v
                            ? 'bg-emerald-600/30 border-emerald-500/60 text-emerald-300'
                            : 'bg-gray-900/40 border-gray-700/60 text-gray-500 hover:border-gray-600 hover:text-gray-300'
                        }`}
                      >
                        {v}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Pacing */}
                <div className="space-y-1">
                  <p className="text-[10px] text-gray-500 font-medium uppercase tracking-wider">Pacing</p>
                  <div className="flex gap-1.5">
                    {(['slow', 'balanced', 'fast'] as const).map((v) => (
                      <button
                        key={v}
                        type="button"
                        onClick={() => setSlControls((p) => ({ ...p, pacing: v }))}
                        className={`flex-1 py-1.5 text-[11px] rounded-lg border transition capitalize ${
                          slControls.pacing === v
                            ? 'bg-emerald-600/30 border-emerald-500/60 text-emerald-300'
                            : 'bg-gray-900/40 border-gray-700/60 text-gray-500 hover:border-gray-600 hover:text-gray-300'
                        }`}
                      >
                        {v}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Length */}
                <div className="space-y-1">
                  <p className="text-[10px] text-gray-500 font-medium uppercase tracking-wider">Length</p>
                  <select
                    value={slControls.length}
                    onChange={(e) => setSlControls((p) => ({ ...p, length: e.target.value }))}
                    className="w-full h-7 px-2 text-xs rounded-lg bg-gray-900/60 border border-gray-800 text-gray-300 focus:outline-none focus:border-emerald-700/50 transition"
                  >
                    <option value="short">Short (~350 w)</option>
                    <option value="medium">Medium (~1 000 w)</option>
                    <option value="long">Long (~2 000 w)</option>
                  </select>
                </div>

                {/* Mode */}
                <div className="space-y-1">
                  <p className="text-[10px] text-gray-500 font-medium uppercase tracking-wider">Mode</p>
                  <select
                    value={mode}
                    onChange={(e) => setMode(e.target.value as 'roleplay' | 'duet' | 'play')}
                    className="w-full h-7 px-2 text-xs rounded-lg bg-gray-900/60 border border-gray-800 text-gray-300 focus:outline-none focus:border-emerald-700/50 transition"
                  >
                    <option value="roleplay">Roleplay</option>
                    <option value="duet">Duet</option>
                    <option value="play">Play</option>
                  </select>
                </div>

                {/* Story progress */}
                <div className="space-y-2.5 pt-2 border-t border-gray-800/40">
                  <div className="flex items-center justify-between">
                    <p className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">Story Progress</p>
                    {isLoadingState && <span className="text-[10px] text-gray-600">Loading...</span>}
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
                        <div key={label} className={dim ? 'opacity-40' : undefined}>
                          <div className="flex justify-between mb-0.5">
                            <span className="text-[10px] text-gray-500">{label}</span>
                            <span className="text-[10px] text-gray-600">{Math.round(value * 100)}%</span>
                          </div>
                          <div className="h-1.5 bg-gray-800/80 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-emerald-600/70 rounded-full transition-[width] duration-500 ease-out"
                              style={{ width: `${value * 100}%` }}
                            />
                          </div>
                        </div>
                      ))}
                      <div className="pt-1.5 border-t border-gray-800/40 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px]">
                        <span className="text-gray-600">Tone</span>
                        <span className="text-gray-400">{storyState.tone}</span>
                        <span className="text-gray-600">Pacing</span>
                        <span className="text-gray-400">{storyState.pacing}</span>
                      </div>
                    </div>
                  ) : (
                    <p className="text-[10px] text-gray-600">
                      {isLoadingState ? 'Loading...' : 'No state loaded.'}
                    </p>
                  )}
                </div>

              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  );
}
