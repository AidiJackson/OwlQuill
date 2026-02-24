/**
 * StoryLabEngine — self-contained collaborate-with-AI writing panel.
 *
 * Left pane:  editable manuscript textarea (storyText state)
 * Right pane: StoryLab controls, suggestions, progress bars, generate buttons
 *
 * story_id is fixed to writespace:none:none until realm/character selectors
 * are added to the /storylab page.
 */
import { useState, useEffect, useRef } from 'react';

// ── Types ─────────────────────────────────────────────────────────────────────

type SLStoryState = {
  tone: string;
  pacing: string;
  stakes: number | string;
  scene_type: string;
  intimacy_level: number;
  tension: number;
  emotional_weight: number;
};
type SLStateJson = {
  story_state: SLStoryState;
  characters: unknown[];
  relationships: unknown[];
};
type SLDelta    = { path: string; delta: number };
type SLControls = {
  direction: string;
  tone_intensity: string;
  pacing: string;
  length: string;
  boundary: string;
};
type SLState = {
  story_summary: string;
  state_json: SLStateJson;
  updated_at: string;
};

// Fixed story_id until realm/character selectors land on /storylab
const STORY_ID = 'writespace:none:none';

// ── Component ─────────────────────────────────────────────────────────────────

export default function StoryLabEngine() {
  // Manuscript text
  const [storyText, setStoryText] = useState('');

  // StoryLab state
  const [storylabState,  setStorylabState]  = useState<SLState | null>(null);
  const [storylabDeltas, setStorylabDeltas] = useState<SLDelta[]>([]);
  const [slControls,     setSlControls]     = useState<SLControls>({
    direction: 'advance_plot',
    tone_intensity: 'moderate',
    pacing: 'balanced',
    length: 'medium',
    boundary: 'sfw',
  });
  const [isLoadingSlState, setIsLoadingSlState] = useState(false);
  const [isGenerating,     setIsGenerating]     = useState(false);
  const [isGeneratingAlt,  setIsGeneratingAlt]  = useState(false);
  const [storylabError,    setStorylabError]    = useState('');

  const slStateAbortRef    = useRef<AbortController | null>(null);
  const slGenerateAbortRef = useRef<AbortController | null>(null);

  // Fetch state on mount
  useEffect(() => {
    void fetchStorylabState(STORY_ID);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── API calls ───────────────────────────────────────────────────────────────

  async function fetchStorylabState(id: string) {
    if (slStateAbortRef.current) slStateAbortRef.current.abort();
    const ctrl = new AbortController();
    slStateAbortRef.current = ctrl;
    setIsLoadingSlState(true);
    setStorylabError('');
    try {
      const resp = await fetch(
        `/api/storylab/state?story_id=${encodeURIComponent(id)}`,
        { signal: ctrl.signal },
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data = await resp.json() as any;
      setStorylabState(data as SLState);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      setStorylabError('Could not load story state.');
    } finally {
      setIsLoadingSlState(false);
    }
  }

  async function generateStorylab(variant: 'default' | 'alt' = 'default') {
    if (!storyText.trim()) {
      setStorylabError('Add some text before generating.');
      return;
    }
    if (slGenerateAbortRef.current) slGenerateAbortRef.current.abort();
    const ctrl = new AbortController();
    slGenerateAbortRef.current = ctrl;
    if (variant === 'alt') { setIsGeneratingAlt(true); } else { setIsGenerating(true); }
    setStorylabError('');
    setStorylabDeltas([]);
    try {
      const payload: Record<string, unknown> = {
        story_id: STORY_ID,
        text: storyText,
        controls: slControls,
      };
      if (variant === 'alt') payload.variant = 'alt';

      const resp = await fetch('/api/storylab/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: ctrl.signal,
      });
      if (!resp.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const errData = await resp.json().catch(() => ({})) as any;
        const raw = errData?.detail?.message || errData?.detail || `HTTP ${resp.status}`;
        throw new Error(typeof raw === 'string' ? raw : JSON.stringify(raw));
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data = await resp.json() as any;
      const generated = (data?.generated?.text as string | undefined) ?? '';
      if (generated) {
        setStoryText((prev) => prev + (prev.endsWith('\n') ? '\n' : '\n\n') + generated);
      }
      if (data?.state) {
        const newStateJson = (data.state.state_json ?? null) as SLStateJson | null;
        setStorylabState((prev) => ({
          story_summary: (data.state.story_summary as string) ?? prev?.story_summary ?? '',
          state_json: (newStateJson ?? prev?.state_json) as SLStateJson,
          updated_at: new Date().toISOString(),
        }));
        setStorylabDeltas((data.state.deltas as SLDelta[]) ?? []);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      setStorylabError((err as Error).message || 'Generation failed.');
    } finally {
      if (variant === 'alt') { setIsGeneratingAlt(false); } else { setIsGenerating(false); }
    }
  }

  // ── Suggestion builder ──────────────────────────────────────────────────────

  const ss = storylabState?.state_json?.story_state;

  function buildSuggestions(state: typeof ss): string[] {
    if (!state) return [];
    const n = (v: number | string | undefined) => (typeof v === 'number' ? v : 0);
    const tension   = n(state.tension);
    const emotional = n(state.emotional_weight);
    const stakes    = n(state.stakes);
    const intimacy  = n(state.intimacy_level);

    type S = { p: number; t: string };
    const pool: S[] = [];

    if (tension < 0.35)                    pool.push({ p: 10, t: "Consider adding friction — a disagreement, interruption, or external pressure." });
    if (tension >= 0.35 && tension < 0.65) pool.push({ p:  7, t: "Introduce a complication to stop the scene from resolving too easily." });
    if (tension >= 0.65)                   pool.push({ p:  9, t: "The pressure is high — use short sentences and concrete sensory detail." });
    if (emotional < 0.35)                  pool.push({ p:  9, t: "Deepen emotion through action and subtext — avoid direct declarations." });
    if (emotional >= 0.65)                 pool.push({ p:  7, t: "Let the emotional weight land through silence or a small physical gesture." });
    if (stakes < 0.4)                      pool.push({ p:  8, t: "Raise the stakes: attach a real consequence to the next choice." });
    if (stakes >= 0.7)                     pool.push({ p:  6, t: "Stakes are established — make a character act against their own interest." });
    if (intimacy >= 0.5)                   pool.push({ p:  7, t: "Let closeness show in proximity and restraint — small details carry more than declarations." });
    if (intimacy < 0.2)                    pool.push({ p:  4, t: "A moment of small vulnerability could deepen the scene's emotional core." });

    pool.sort((a, b) => b.p - a.p);
    const out = pool.slice(0, 3).map((s) => s.t);
    if (out.length === 0) out.push("Begin the next beat with a specific sensory detail to ground the scene.");
    return out;
  }

  const suggestions = buildSuggestions(ss);

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col md:flex-row gap-4 md:gap-6 p-4 md:p-6 min-h-0 flex-1">

      {/* ── Manuscript pane ─────────────────────────────────────────────── */}
      <div className="flex flex-col flex-1 min-h-0">
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Manuscript</p>
          <span className="text-[10px] text-gray-600">
            {storyText.trim() ? `${storyText.match(/[A-Za-z0-9\u2019']+/g)?.length ?? 0} words` : 'Empty'}
          </span>
        </div>
        <textarea
          value={storyText}
          onChange={(e) => setStoryText(e.target.value)}
          placeholder="Begin your story here, or generate a continuation to get started…"
          className="flex-1 min-h-[300px] md:min-h-0 w-full resize-none rounded-xl bg-gray-900/60 border border-gray-800/70 ring-1 ring-black/10 shadow-[0_8px_30px_rgba(0,0,0,0.25)] p-5 text-[15px] leading-[1.75] font-normal tracking-[0.01em] text-gray-100 placeholder-gray-700 focus:outline-none focus:border-gray-700 transition"
        />
      </div>

      {/* ── Controls pane ───────────────────────────────────────────────── */}
      <div className="w-full md:w-[320px] shrink-0 overflow-y-auto space-y-3">

        {/* StoryLab suggests */}
        {isLoadingSlState && !ss ? (
          <div className="border border-gray-800 rounded-xl p-4 space-y-2.5 animate-pulse">
            <div className="h-2.5 w-28 bg-gray-800 rounded" />
            <div className="h-2 bg-gray-800/80 rounded w-full" />
            <div className="h-2 bg-gray-800/80 rounded w-5/6" />
            <div className="h-2 bg-gray-800/80 rounded w-4/6" />
          </div>
        ) : ss ? (
          <div className="border border-gray-800 rounded-xl p-4 space-y-2">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">StoryLab suggests</p>
            <ul className="space-y-1.5">
              {suggestions.map((s, i) => (
                <li key={i} className="flex gap-2 text-xs text-gray-300 leading-relaxed">
                  <span className="mt-0.5 shrink-0 text-emerald-500">›</span>
                  <span>{s}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {/* Controls */}
        <div className="border border-gray-800 rounded-xl p-4 space-y-4">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Controls</p>

          {/* Direction — grouped chips */}
          <div className="space-y-2">
            <p className="text-xs text-gray-500">Direction</p>
            {(
              [
                { group: 'Emotion',    chips: [{ value: 'sad_moment', label: 'Sad Moment' }, { value: 'quiet_reflection', label: 'Reflective' }] },
                { group: 'Conflict',   chips: [{ value: 'argument_begins', label: 'Argument' }, { value: 'twist_event', label: 'Twist' }] },
                { group: 'Movement',   chips: [{ value: 'advance_plot', label: 'Advance Plot' }, { value: 'action_sequence', label: 'Action' }, { value: 'add_dialogue', label: 'Dialogue' }] },
                { group: 'Connection', chips: [{ value: 'romantic_moment', label: 'Romantic' }, { value: 'sensual_scene', label: 'Sensual' }, { value: 'intimate_scene', label: 'Intimate' }] },
              ] as { group: string; chips: { value: string; label: string }[] }[]
            ).map(({ group, chips }) => (
              <div key={group} className="space-y-1">
                <p className="text-[10px] text-gray-600 uppercase tracking-wider">{group}</p>
                <div className="flex flex-wrap gap-1.5">
                  {chips.map(({ value, label }) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setSlControls((p) => ({ ...p, direction: value }))}
                      className={`px-2.5 py-1 text-xs rounded-lg border transition ${
                        slControls.direction === value
                          ? 'bg-emerald-600/30 border-emerald-500/60 text-emerald-300'
                          : 'bg-gray-900/40 border-gray-700/60 text-gray-400 hover:border-gray-600 hover:text-gray-300'
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
            <p className="text-xs text-gray-500">Boundary</p>
            <select
              value={slControls.boundary}
              onChange={(e) => setSlControls((p) => ({ ...p, boundary: e.target.value }))}
              className="input text-sm w-full"
            >
              <option value="sfw">SFW</option>
              <option value="fade_to_black">Fade to black</option>
              <option value="sensual">Sensual</option>
            </select>
          </div>

          {/* Tone chips */}
          <div className="space-y-1">
            <p className="text-xs text-gray-500">Tone</p>
            <div className="flex gap-1.5">
              {([{ value: 'light', label: 'Light' }, { value: 'moderate', label: 'Moderate' }, { value: 'intense', label: 'Intense' }] as const).map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setSlControls((p) => ({ ...p, tone_intensity: value }))}
                  className={`flex-1 py-1 text-xs rounded-lg border transition ${
                    slControls.tone_intensity === value
                      ? 'bg-emerald-600/30 border-emerald-500/60 text-emerald-300'
                      : 'bg-gray-900/40 border-gray-700/60 text-gray-400 hover:border-gray-600 hover:text-gray-300'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Pacing chips */}
          <div className="space-y-1">
            <p className="text-xs text-gray-500">Pacing</p>
            <div className="flex gap-1.5">
              {([{ value: 'slow', label: 'Slow' }, { value: 'balanced', label: 'Balanced' }, { value: 'fast', label: 'Fast' }] as const).map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setSlControls((p) => ({ ...p, pacing: value }))}
                  className={`flex-1 py-1 text-xs rounded-lg border transition ${
                    slControls.pacing === value
                      ? 'bg-emerald-600/30 border-emerald-500/60 text-emerald-300'
                      : 'bg-gray-900/40 border-gray-700/60 text-gray-400 hover:border-gray-600 hover:text-gray-300'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Length */}
          <div className="space-y-1">
            <p className="text-xs text-gray-500">Length</p>
            <select
              value={slControls.length}
              onChange={(e) => setSlControls((p) => ({ ...p, length: e.target.value }))}
              className="input text-xs w-full"
            >
              <option value="short">Short</option>
              <option value="medium">Medium</option>
              <option value="long">Long</option>
            </select>
          </div>
        </div>

        {/* Generate buttons */}
        <div className="space-y-1.5">
          <button
            type="button"
            onClick={() => void generateStorylab()}
            disabled={isGenerating || isGeneratingAlt || !storyText.trim()}
            className="w-full py-2 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white font-semibold text-sm transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isGenerating ? 'Generating\u2026' : 'Continue with StoryLab'}
          </button>
          <button
            type="button"
            onClick={() => void generateStorylab('alt')}
            disabled={isGenerating || isGeneratingAlt || !storyText.trim()}
            className="w-full py-1.5 px-4 rounded-xl border border-gray-700/60 bg-gray-900/40 hover:bg-gray-800/50 hover:border-gray-600 text-gray-400 hover:text-gray-300 text-sm transition disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {isGeneratingAlt ? 'Generating\u2026' : 'Try another version'}
          </button>
        </div>

        {storylabError && (
          <p className="text-xs text-red-400">{storylabError}</p>
        )}

        {/* What changed */}
        {storylabDeltas.length > 0 && (
          <div className="border border-gray-800 rounded-xl p-3 space-y-1">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">What changed</p>
            <ul className="space-y-0.5">
              {storylabDeltas.map((d, i) => (
                <li key={i} className="flex justify-between text-xs">
                  <span className="text-gray-500">{d.path.split('.').pop()}</span>
                  <span className={d.delta >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                    {d.delta > 0 ? '+' : ''}{d.delta.toFixed(2)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Story progress */}
        <div className="border border-gray-800 rounded-xl p-3 space-y-2.5">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Story Progress</p>
            {isLoadingSlState && <span className="text-xs text-gray-500">Loading\u2026</span>}
          </div>
          {ss ? (() => {
            const clamp = (v: number | string | undefined) =>
              Math.min(1, Math.max(0, typeof v === 'number' ? v : 0));
            const bars: { label: string; value: number; dim?: boolean }[] = [
              { label: 'Emotion',  value: clamp(ss.emotional_weight) },
              { label: 'Tension',  value: clamp(ss.tension) },
              { label: 'Stakes',   value: clamp(ss.stakes) },
              { label: 'Intimacy', value: clamp(ss.intimacy_level), dim: slControls.boundary === 'sfw' },
            ];
            return (
              <div className="space-y-2">
                {bars.map(({ label, value, dim }) => (
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
                <div className="pt-1 border-t border-gray-800/60 grid grid-cols-2 gap-x-4 gap-y-0.5 text-[10px]">
                  <span className="text-gray-600">Tone</span>
                  <span className="text-gray-400">{ss.tone}</span>
                  <span className="text-gray-600">Pacing</span>
                  <span className="text-gray-400">{ss.pacing}</span>
                </div>
              </div>
            );
          })() : (
            <p className="text-xs text-gray-500">
              {isLoadingSlState ? 'Loading\u2026' : 'No state loaded.'}
            </p>
          )}
        </div>

      </div>
    </div>
  );
}
