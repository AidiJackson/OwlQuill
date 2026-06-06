import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Sparkles, Shield, Lock, CheckCircle2, Clock, XCircle, Loader2, ImageIcon } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import { useAuthStore } from '@/lib/store';
import type { Character, AdultStudioStatus, AdultStudioGenerateResult } from '@/lib/types';

/**
 * 18+ Studio — first working pipeline path.
 *
 * SEPARATE from Canon Studio. Reads the locked Canon Pack as source truth via
 * the /adult-studio endpoints. Prepare builds an identity manifest; Generate
 * runs an adult-specific, identity-conditioned generation through the Adult
 * Studio backend (never the Canon Studio generator). No silent text fallback.
 */

type StudioStatus = AdultStudioStatus['status'];

const STATUS_META: Record<
  StudioStatus,
  { label: string; icon: typeof Clock; cls: string }
> = {
  not_trained: { label: 'Not trained', icon: Clock, cls: 'text-gray-400 border-gray-700 bg-gray-800/40' },
  preparing: { label: 'Preparing', icon: Loader2, cls: 'text-amber-300 border-amber-800/50 bg-amber-900/20' },
  ready: { label: 'Ready', icon: CheckCircle2, cls: 'text-emerald-300 border-emerald-800/50 bg-emerald-900/20' },
  failed: { label: 'Failed', icon: XCircle, cls: 'text-red-300 border-red-800/50 bg-red-900/20' },
};

/** Short human-readable identity status derived from canon state. */
function identityStatus(c: Character): string {
  if (c.visual_locked) {
    const h = c.identity_health;
    if (h && (h.face === 'stale' || h.body === 'stale' || h.tattoos === 'stale')) {
      return 'Canon locked · needs refresh';
    }
    return 'Canon locked';
  }
  return 'Canon not locked';
}

export default function Studio18Plus() {
  const isAdmin = useAuthStore((s) => !!s.user?.is_admin);

  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Per-character 18+ identity status (from the backend).
  const [statusByChar, setStatusByChar] = useState<Record<number, AdultStudioStatus>>({});
  const [preparing, setPreparing] = useState(false);
  const [prepareError, setPrepareError] = useState('');

  // Generation state.
  const [prompt, setPrompt] = useState('');
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<AdultStudioGenerateResult | null>(null);
  const [genError, setGenError] = useState('');
  const [genMeta, setGenMeta] = useState<AdultStudioGenerateResult | null>(null);

  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    apiClient
      .getCharacters()
      .then((chars) => {
        if (!mountedRef.current) return;
        setCharacters(chars);
        if (chars.length === 1) setSelectedId(chars[0].id);
      })
      .catch((err) => {
        if (mountedRef.current) setLoadError(err instanceof Error ? err.message : 'Failed to load characters');
      })
      .finally(() => {
        if (mountedRef.current) setLoading(false);
      });
  }, []);

  // Load 18+ status for the selected character, and reset generation UI.
  useEffect(() => {
    setPrepareError('');
    setGenError('');
    setGenMeta(null);
    setResult(null);
    setPrompt('');
    if (selectedId == null || statusByChar[selectedId]) return;
    apiClient
      .getAdultStudioStatus(selectedId)
      .then((s) => { if (mountedRef.current) setStatusByChar((p) => ({ ...p, [selectedId]: s })); })
      .catch(() => {});
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  const selected = characters.find((c) => c.id === selectedId) ?? null;
  const studio: AdultStudioStatus | undefined = selectedId != null ? statusByChar[selectedId] : undefined;
  const status: StudioStatus = studio?.status ?? 'not_trained';

  const handlePrepare = async () => {
    if (!selected) return;
    setPreparing(true);
    setPrepareError('');
    // Optimistic "Preparing" card state.
    setStatusByChar((p) => ({
      ...p,
      [selected.id]: { ...(p[selected.id] ?? { character_id: selected.id, refs_count: 0, marks_count: 0 }), status: 'preparing' },
    }));
    try {
      const s = await apiClient.prepareAdultStudio(selected.id);
      if (mountedRef.current) setStatusByChar((p) => ({ ...p, [selected.id]: s }));
    } catch (err) {
      if (!mountedRef.current) return;
      setPrepareError(err instanceof Error ? err.message : 'Failed to prepare 18+ identity');
      setStatusByChar((p) => ({
        ...p,
        [selected.id]: { ...(p[selected.id] ?? { character_id: selected.id, refs_count: 0, marks_count: 0 }), status: 'failed' },
      }));
    } finally {
      if (mountedRef.current) setPreparing(false);
    }
  };

  const handleGenerate = async () => {
    if (!selected || !prompt.trim()) return;
    setGenerating(true);
    setGenError('');
    setGenMeta(null);
    setResult(null);
    try {
      const res = await apiClient.generateAdultStudioImage(selected.id, prompt.trim());
      if (mountedRef.current) { setResult(res); setGenMeta(res); }
    } catch (err) {
      if (!mountedRef.current) return;
      setGenError(err instanceof Error ? err.message : 'Generation failed');
      const meta = (err as { meta?: AdultStudioGenerateResult }).meta;
      if (meta) setGenMeta(meta);
    } finally {
      if (mountedRef.current) setGenerating(false);
    }
  };

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <div className="border-b border-gray-800 bg-gray-900/50">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link to="/images" className="text-gray-400 hover:text-gray-200 transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <span className="text-sm font-medium text-gray-300">18+ Studio</span>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-8 space-y-8">
        {/* ── Header / purpose ─────────────────────────────────────── */}
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <div className="rounded-xl bg-fuchsia-900/30 border border-fuchsia-800/40 p-2.5">
              <Sparkles className="w-5 h-5 text-fuchsia-300" />
            </div>
            <h1 className="text-xl font-semibold text-gray-100">18+ Studio</h1>
          </div>
          <p className="text-sm leading-relaxed text-gray-300">
            18+ Studio is designed for mature, swimwear, lingerie, underwear, and
            adult-adjacent character scenes using stronger identity-locking technology.
          </p>
        </div>

        {/* ── Character selector ───────────────────────────────────── */}
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-gray-300">Choose a character</h2>

          {loading ? (
            <p className="text-sm text-gray-500">Loading your characters…</p>
          ) : loadError ? (
            <p className="text-sm text-red-400 bg-red-400/10 rounded-lg px-4 py-2">{loadError}</p>
          ) : characters.length === 0 ? (
            <div className="rounded-lg border border-gray-800 bg-gray-900/50 px-4 py-4 text-sm text-gray-400">
              You don't have any characters yet.{' '}
              <Link to="/characters/new" className="text-emerald-400 hover:text-emerald-300">
                Create one
              </Link>{' '}
              to get started.
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              {characters.map((c) => {
                const isSel = c.id === selectedId;
                return (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => setSelectedId(c.id)}
                    className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border text-left transition-colors ${
                      isSel
                        ? 'border-fuchsia-700 bg-fuchsia-900/20'
                        : 'border-gray-800 bg-gray-900/50 hover:border-gray-700'
                    }`}
                  >
                    {c.avatar_url ? (
                      <img
                        src={c.avatar_url}
                        alt={c.name}
                        className="w-10 h-10 rounded-lg object-cover flex-shrink-0"
                        onError={(e) => { e.currentTarget.style.display = 'none'; }}
                      />
                    ) : (
                      <div className="w-10 h-10 rounded-lg bg-gray-800 flex-shrink-0" />
                    )}
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-100 truncate">{c.name}</p>
                      <p className="text-xs text-gray-500 flex items-center gap-1 truncate">
                        {c.visual_locked && <Lock className="w-3 h-3 flex-shrink-0" />}
                        {identityStatus(c)}
                      </p>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </section>

        {/* ── Identity status + prepare ────────────────────────────── */}
        {selected && (
          <section className="space-y-3">
            <h2 className="text-sm font-medium text-gray-300">18+ identity status</h2>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {(Object.keys(STATUS_META) as StudioStatus[]).map((key) => {
                const meta = STATUS_META[key];
                const Icon = meta.icon;
                const active = status === key;
                return (
                  <div
                    key={key}
                    className={`flex flex-col items-center gap-1 rounded-lg border px-2 py-3 text-xs transition-opacity ${
                      active ? meta.cls : 'text-gray-600 border-gray-800 bg-gray-900/40 opacity-60'
                    }`}
                  >
                    <Icon className={`w-4 h-4 ${active && key === 'preparing' ? 'animate-spin' : ''}`} />
                    {meta.label}
                  </div>
                );
              })}
            </div>

            <button
              type="button"
              onClick={handlePrepare}
              disabled={preparing || status === 'preparing'}
              className="btn btn-primary text-sm disabled:opacity-50"
            >
              {preparing || status === 'preparing' ? 'Preparing…' : 'Prepare 18+ Identity'}
            </button>

            {prepareError && (
              <p className="text-sm text-amber-400 bg-amber-950/40 border border-amber-800/40 rounded-lg px-4 py-2">
                {prepareError}
              </p>
            )}

            {status === 'ready' && (
              <p className="text-sm text-gray-400 bg-gray-900/50 border border-gray-800 rounded-lg px-4 py-3">
                Identity manifest ready from the locked canon pack
                {studio ? ` — ${studio.refs_count} reference image(s), ${studio.marks_count} marking(s).` : '.'}
              </p>
            )}
          </section>
        )}

        {/* ── Generation (only when Ready) ─────────────────────────── */}
        {selected && status === 'ready' && (
          <section className="space-y-3">
            <h2 className="text-sm font-medium text-gray-300">Generate in 18+ Studio</h2>
            <textarea
              className="textarea w-full"
              rows={3}
              maxLength={800}
              placeholder="Describe the adult-adjacent scene (e.g. swimwear, lingerie, beach)…"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              disabled={generating}
            />
            <button
              type="button"
              onClick={handleGenerate}
              disabled={generating || !prompt.trim()}
              className="btn btn-primary text-sm flex items-center gap-2 disabled:opacity-50"
            >
              {generating ? (
                <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Generating…</>
              ) : (
                <><ImageIcon className="w-3.5 h-3.5" /> Generate in 18+ Studio</>
              )}
            </button>

            {genError && (
              <p className="text-sm text-amber-400 bg-amber-950/40 border border-amber-800/40 rounded-lg px-4 py-2">
                {genError}
              </p>
            )}

            {result && (
              <div className="rounded-lg border border-gray-800 overflow-hidden bg-gray-900 max-w-xs">
                <img src={result.image_url} alt="18+ Studio result" className="w-full object-cover" />
              </div>
            )}

            {/* Admin metadata — provider / refs / multi-image / failure reason. */}
            {isAdmin && genMeta && (
              <div className="rounded-lg border border-gray-800 bg-gray-900/50 px-4 py-3 text-xs text-gray-400 space-y-0.5">
                <p className="font-medium uppercase tracking-wide text-gray-500 mb-1 flex items-center gap-1.5">
                  <Shield className="w-3.5 h-3.5" /> Admin · generation metadata
                </p>
                <p>provider: <span className="text-gray-300">{genMeta.provider}</span></p>
                <p>model_ref: <span className="text-gray-300">{genMeta.model_ref ?? '—'}</span></p>
                <p>refs_count: <span className="text-gray-300">{genMeta.refs_count}</span></p>
                <p>multi_image_used: <span className="text-gray-300">{String(genMeta.multi_image_used)}</span></p>
                <p>used_refs: <span className="text-gray-300">{genMeta.used_refs?.join(', ') || '—'}</span></p>
                <p>failure_reason: <span className="text-gray-300">{genMeta.failure_reason ?? 'none'}</span></p>
              </div>
            )}
          </section>
        )}

        {/* ── Admin-only tech direction panel ──────────────────────── */}
        {isAdmin && (
          <section className="space-y-2">
            <div className="rounded-lg border border-gray-800 bg-gray-900/50 px-4 py-3">
              <p className="text-xs font-medium uppercase tracking-wide text-gray-500 mb-2 flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5" />
                Admin · tech direction
              </p>
              <p className="text-sm text-gray-400 mb-1">Future pipeline candidates:</p>
              <ul className="text-sm text-gray-400 list-disc list-inside space-y-0.5">
                <li>InstantID</li>
                <li>PhotoMaker</li>
                <li>PuLID</li>
                <li>IP-Adapter FaceID</li>
                <li>Character LoRA</li>
                <li>ComfyUI / managed GPU pipeline</li>
              </ul>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
