import { useEffect, useRef, useState } from 'react';
import { ImageIcon, RefreshCw, ZoomIn, X } from 'lucide-react';
import type {
  V2PackResponse,
  V2PackCard,
  V2PackJob,
  IdentityPackResponse,
  IdentitySpec,
  BodyMorphology,
} from '../shared/types';
import { V2_SLOT_LABELS, BODY_HEIGHT_OPTIONS, BODY_BUILD_OPTIONS } from '../shared/types';
import {
  startV2PackJob,
  getV2PackJob,
  getLatestV2PackJob,
  patchBodyCanon,
  generateIdentityPack,
  resolveImageUrl,
} from '../shared/api';

interface Props {
  characterId: number;
  vibeText: string;
  identitySpec?: IdentitySpec | null;
  bodyMorphology: BodyMorphology;
  onBodyMorphologyChange: (m: BodyMorphology) => void;
  pack: V2PackResponse | null;
  onPackGenerated: (pack: V2PackResponse) => void;
  onNext: () => void;
  onBack: () => void;
}

// Section ordering for the grouped review grid.
const FACE_ORDER = ['face_front', 'face_left_3q', 'face_right_3q', 'face_profile', 'face_expression'];
const BODY_ORDER = [
  'body_front', 'body_left', 'body_right', 'body_back',
  'torso_front', 'torso_side', 'standing_relaxed', 'seated_relaxed',
];

/** DEV-only escape hatch: map a legacy 4-anchor pack into the v2 shape. */
function legacyToV2(p: IdentityPackResponse): V2PackResponse {
  return {
    pack_id: p.pack_id,
    dry_run: false,
    cards: p.images.map((im) => {
      const role = (im.metadata_json?.pack_role as string) || '';
      return { slot: role, section: 'face', role, url: im.url, status: 'generated' };
    }),
    marks: [],
    total_spend: 0,
    image_count: p.images.length,
    regenerations: [],
    openai_fallback: [],
    gate_failed: [],
    errors: [],
    clean_pass: true,
  };
}

/** Extract a human-meaningful message from a thrown value, with a fallback. */
function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === 'string' && err) return err;
  return fallback;
}

export default function StepGeneratePack({
  characterId,
  vibeText,
  identitySpec,
  bodyMorphology,
  onBodyMorphologyChange,
  pack,
  onPackGenerated,
  onNext,
  onBack,
}: Props) {
  const [loading, setLoading] = useState(false); // submit phase only (job does the long work)
  const [job, setJob] = useState<V2PackJob | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [enlarged, setEnlarged] = useState<string | null>(null);
  // One idempotency key per generate click — server returns the same job for
  // any accidental resubmission of the same click (double-click, retry, refresh).
  const idempotencyKeyRef = useRef<string | null>(null);
  // Set when a completed job's result has been handed to the wizard, so
  // polling/rediscovery never re-applies it.
  const deliveredJobRef = useRef<string | null>(null);

  // Debug fallback: legacy 4-anchor path stays reachable only via this DEV flag,
  // never as the default. Production users always get the v2 canon pack.
  const legacyDebug =
    import.meta.env.DEV && localStorage.getItem('useLegacyPack') === '1';

  const jobActive = !!job && (job.status === 'queued' || job.status === 'running');
  const busy = loading || jobActive;

  /** Apply a terminal job to the UI exactly once. */
  const applyTerminalJob = (j: V2PackJob) => {
    if (j.status === 'completed') {
      if (deliveredJobRef.current !== j.job_id && j.result) {
        deliveredJobRef.current = j.job_id;
        if (j.result.stopped) {
          setError('Generation stopped early. Please try again.');
        }
        onPackGenerated(j.result);
      }
    } else if (j.status === 'failed') {
      setError(j.error_message || "We couldn't generate the images right now. Please try again.");
    }
  };

  // Poll the active job while this step is mounted. Closing the tab never
  // cancels the server-side generation — remounting rediscovers it below.
  useEffect(() => {
    if (!jobActive || !job) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const next = await getV2PackJob(characterId, job.job_id);
        if (cancelled) return;
        setJob(next);
        if (next.status === 'completed' || next.status === 'failed') {
          applyTerminalJob(next);
        }
      } catch (pollErr) {
        // Transient poll failures are silent — the next tick retries.
        console.error('[StepGeneratePack] job poll failed', pollErr);
      }
    };
    const id = window.setInterval(tick, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [characterId, job?.job_id, jobActive]);

  // Refresh recovery: on mount, rediscover an in-flight job (resume polling)
  // or a completed pack this browser never displayed.
  useEffect(() => {
    if (legacyDebug) return;
    let cancelled = false;
    (async () => {
      try {
        const latest = await getLatestV2PackJob(characterId);
        if (cancelled || !latest) return;
        if (latest.status === 'queued' || latest.status === 'running') {
          setJob(latest);
        } else if (
          latest.status === 'completed' &&
          !pack &&
          latest.result &&
          !latest.superseded
        ) {
          // Only adopt a completed pack that has NOT already been accepted —
          // a superseded snapshot may no longer match the live canon slots.
          setJob(latest);
          applyTerminalJob(latest);
        }
      } catch (discoverErr) {
        console.error('[StepGeneratePack] active-job discovery failed', discoverErr);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [characterId]);

  const handleGenerate = async () => {
    if (busy) return;
    setLoading(true);
    setError('');
    setNotice('');

    // DEV-only legacy path stays isolated from the v2 flow.
    if (legacyDebug) {
      try {
        const spec: IdentitySpec | null = identitySpec
          ? { ...identitySpec, body_height: bodyMorphology.height, body_build: bodyMorphology.build }
          : null;
        const legacy = await generateIdentityPack(characterId, undefined, vibeText, spec);
        onPackGenerated(legacyToV2(legacy));
      } catch (err) {
        console.error('[StepGeneratePack] legacy pack generation failed', err);
        setError(errorMessage(err, "We couldn't generate the images right now. Please try again."));
      } finally {
        setLoading(false);
      }
      return;
    }

    // Step 1 — persist body morphology so v2 generation grounds on it. A failure
    // here is distinct from a generation failure and never reaches the canon.
    try {
      await patchBodyCanon(characterId, {
        height: bodyMorphology.height,
        build: bodyMorphology.build,
      });
    } catch (err) {
      console.error('[StepGeneratePack] patchBodyCanon failed', err);
      setError(errorMessage(err, "We couldn't save your body settings. Please try again."));
      setLoading(false);
      return;
    }

    // Step 2 — submit the async job. Returns in well under a second; the
    // polling effect above takes over from here.
    try {
      if (!idempotencyKeyRef.current) {
        idempotencyKeyRef.current =
          window.crypto?.randomUUID?.() ?? `${characterId}-${Date.now()}`;
      }
      const submitted = await startV2PackJob(characterId, {
        maxSpend: 8,
        idempotencyKey: idempotencyKeyRef.current,
      });
      setJob(submitted);
      if (submitted.status === 'completed' || submitted.status === 'failed') {
        // Idempotent resubmission of an already-finished job.
        applyTerminalJob(submitted);
      }
    } catch (submitErr) {
      console.error('[StepGeneratePack] job submission failed', submitErr);
      setError(errorMessage(submitErr, "We couldn't start the generation. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  const handleRetry = () => {
    // A fresh attempt gets a fresh idempotency key; the previous failed job
    // stays terminal and can never be re-run by polling.
    idempotencyKeyRef.current = null;
    setJob(null);
    void handleGenerate();
  };

  const cardBySlot = new Map<string, V2PackCard>();
  (pack?.cards ?? []).forEach((c) => cardBySlot.set(c.slot, c));

  const renderSection = (title: string, slots: string[]) => (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-ink-2">{title}</h3>
      <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
        {slots.map((slot) => {
          const card = cardBySlot.get(slot);
          const url = card?.url ? resolveImageUrl(card.url) : null;
          return (
            <div key={slot} className="rounded-lg overflow-hidden border border-edge">
              {url ? (
                <button
                  type="button"
                  onClick={() => setEnlarged(url)}
                  className="block w-full relative group"
                >
                  <img src={url} alt={V2_SLOT_LABELS[slot] || slot} className="w-full aspect-[2/3] object-cover" />
                  <div className="absolute top-1.5 right-1.5 p-1 rounded-full bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
                    <ZoomIn className="w-3 h-3" />
                  </div>
                </button>
              ) : (
                <div className="w-full aspect-[2/3] bg-surface-elevated flex items-center justify-center">
                  <span className="text-[10px] text-ink-3">—</span>
                </div>
              )}
              <div className="px-1.5 py-1 text-center bg-surface">
                <span className="text-[11px] text-ink-2">{V2_SLOT_LABELS[slot] || slot}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="text-center space-y-2">
        <div className="mx-auto w-12 h-12 rounded-full bg-gem-soft flex items-center justify-center">
          <ImageIcon className="w-6 h-6 text-gem" />
        </div>
        <h2 className="text-xl font-semibold text-ink">Generate Identity Pack</h2>
        <p className="text-sm text-ink-2">
          We'll create your character's full visual canon — face, body, and details.
        </p>
      </div>

      {/* Body Identity (applied to the whole pack) */}
      <div className="border border-edge rounded-lg px-4 py-4 space-y-4">
        <p className="text-sm font-medium text-ink-2">Body Identity</p>
        <div className="space-y-1.5">
          <span className="text-xs font-medium text-ink-2">Height</span>
          <div className="flex gap-2">
            {BODY_HEIGHT_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => onBodyMorphologyChange({ ...bodyMorphology, height: opt.value })}
                className={`px-3 py-1 rounded text-xs font-medium border transition-colors ${
                  bodyMorphology.height === opt.value
                    ? 'bg-gem border-gem/50 text-white'
                    : 'bg-surface-elevated border-edge-md text-ink-2 hover:border-edge-md'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
        <div className="space-y-1.5">
          <span className="text-xs font-medium text-ink-2">Build</span>
          <div className="flex flex-wrap gap-2">
            {BODY_BUILD_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => onBodyMorphologyChange({ ...bodyMorphology, build: opt.value })}
                className={`px-3 py-1 rounded text-xs font-medium border transition-colors ${
                  bodyMorphology.build === opt.value
                    ? 'bg-gem border-gem/50 text-white'
                    : 'bg-surface-elevated border-edge-md text-ink-2 hover:border-edge-md'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="text-center space-y-1">
        <p className="text-sm font-medium text-ink-2">
          Locking facial identity first — outfits come next.
        </p>
        <p className="text-xs text-ink-3">
          This pack creates your character's visual canon (13 reference cards).
        </p>
      </div>

      <div className="flex justify-center">
        <button className="btn btn-primary flex items-center gap-2" onClick={handleGenerate} disabled={busy}>
          {busy ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              {job?.status === 'queued' ? 'Queued…' : 'Generating your canon pack…'}
            </>
          ) : pack ? (
            <>
              <RefreshCw className="w-4 h-4" />
              Regenerate Pack
            </>
          ) : (
            'Generate Identity Pack'
          )}
        </button>
      </div>

      {jobActive && (
        <div className="max-w-sm mx-auto space-y-2" aria-live="polite">
          <div className="h-1.5 rounded-full bg-surface-elevated overflow-hidden">
            <div
              className="h-full bg-gem rounded-full transition-all duration-700"
              style={{ width: `${Math.max(2, job?.progress_percent ?? 0)}%` }}
            />
          </div>
          <p className="text-xs text-ink-2 text-center">
            {job?.progress_message || 'Waiting to start…'}
            {' '}— you can safely leave this page; generation continues in the background.
          </p>
        </div>
      )}

      {notice && !error && (
        <div className="text-center">
          <p className="text-sm text-gem bg-gem-soft border border-gem/30 rounded-lg px-4 py-2">
            {notice}
          </p>
        </div>
      )}

      {error && (
        <div className="text-center space-y-2">
          <p className="text-sm text-ink-2 bg-surface-elevated rounded-lg px-4 py-2">{error}</p>
          <button
            type="button"
            className="text-xs text-gem hover:opacity-80 transition-colors"
            onClick={handleRetry}
            disabled={busy}
          >
            Try again
          </button>
        </div>
      )}

      {busy && (
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
          {Array.from({ length: 13 }).map((_, i) => (
            <div key={i} className="rounded-lg overflow-hidden border border-edge">
              <div className="w-full aspect-[2/3] bg-surface-elevated animate-pulse" />
            </div>
          ))}
        </div>
      )}

      {!busy && pack && (
        <div className="space-y-5">
          {renderSection('Face', FACE_ORDER)}
          {renderSection('Body', BODY_ORDER)}
          {pack.marks.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-ink-2">Details</h3>
              <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                {pack.marks.map((m) => {
                  const url = m.detail_crop_url ? resolveImageUrl(m.detail_crop_url) : null;
                  return (
                    <div key={m.mark_id} className="rounded-lg overflow-hidden border border-edge">
                      {url ? (
                        <button type="button" onClick={() => setEnlarged(url)} className="block w-full">
                          <img src={url} alt={m.label} className="w-full aspect-[2/3] object-cover" />
                        </button>
                      ) : (
                        <div className="w-full aspect-[2/3] bg-surface-elevated" />
                      )}
                      <div className="px-1.5 py-1 text-center bg-surface">
                        <span className="text-[11px] text-ink-2 truncate block">{m.label}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {enlarged && (
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
          onClick={() => setEnlarged(null)}
        >
          <div className="relative max-w-md w-full" onClick={(e) => e.stopPropagation()}>
            <img src={enlarged} alt="Enlarged preview" className="w-full rounded-lg" />
            <button
              type="button"
              onClick={() => setEnlarged(null)}
              className="absolute top-3 right-3 p-1.5 rounded-full bg-black/60 text-white hover:bg-black/80 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      <div className="flex justify-between pt-2">
        <button className="btn btn-secondary" onClick={onBack}>
          Back
        </button>
        <button className="btn btn-primary" disabled={!pack || loading} onClick={onNext}>
          Next
        </button>
      </div>
    </div>
  );
}
