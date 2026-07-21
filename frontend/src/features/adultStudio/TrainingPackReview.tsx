import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, XCircle, Clock, AlertTriangle, Loader2, ImageIcon, RotateCcw, Maximize2, X } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { TrainingPackReview as TrainingPackReviewData, TrainingCandidate, TrainingCandidateStatus } from '@/lib/types';

/**
 * S24W — Adult LoRA v4 Training Pack Review (admin-only, Summer-only).
 *
 * Shows every staged candidate from scripts/summer_lora_v4_pack_candidates/ in a
 * grid; each card has approve / reject controls, and clicking the image opens a
 * full-size lightbox (S24W.1) for close inspection. Decisions persist into the
 * pack manifest.json (no DB this sprint), so a refresh keeps statuses. This
 * surface never trains, regenerates, or exports a final pack.
 */

const STATUS_META: Record<TrainingCandidateStatus, { label: string; cls: string; Icon: typeof Clock }> = {
  pending_review: { label: 'Pending', cls: 'text-ink-2 border-edge-md bg-surface-elevated', Icon: Clock },
  approved: { label: 'Approved', cls: 'text-gem border-gem/30 bg-gem-soft', Icon: CheckCircle2 },
  rejected: { label: 'Rejected', cls: 'text-red-300 border-red-800/50 bg-red-900/20', Icon: XCircle },
  failed: { label: 'Failed', cls: 'text-amber-300 border-amber-800/50 bg-amber-900/20', Icon: AlertTriangle },
};

function StatusBadge({ status }: { status: TrainingCandidateStatus }) {
  const m = STATUS_META[status];
  const Icon = m.Icon;
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] ${m.cls}`}>
      <Icon className="w-3 h-3" /> {m.label}
    </span>
  );
}

/**
 * Blob-load the admin-gated candidate image into an object URL, revoking it on
 * unmount / role change. Shared by the grid card and the lightbox so cleanup is
 * identical in both places.
 */
function useCandidateImage(characterId: number, role: string) {
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [imgError, setImgError] = useState(false);

  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    setImgUrl(null);
    setImgError(false);
    apiClient
      .getTrainingCandidateImageUrl(characterId, role)
      .then((u) => {
        if (cancelled) { URL.revokeObjectURL(u); return; }
        url = u;
        setImgUrl(u);
      })
      .catch(() => { if (!cancelled) setImgError(true); });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [characterId, role]);

  return { imgUrl, imgError };
}

function CandidateCard({
  characterId,
  candidate,
  onReview,
  onOpen,
}: {
  characterId: number;
  candidate: TrainingCandidate;
  onReview: (role: string, status: TrainingCandidateStatus) => Promise<void>;
  onOpen: () => void;
}) {
  const { imgUrl, imgError } = useCandidateImage(characterId, candidate.role);
  const [busy, setBusy] = useState(false);

  const click = async (status: TrainingCandidateStatus) => {
    setBusy(true);
    try {
      await onReview(candidate.role, status);
    } finally {
      setBusy(false);
    }
  };

  const isFailed = candidate.status === 'failed';

  return (
    <div className="rounded-lg border border-edge bg-surface overflow-hidden flex flex-col">
      <button
        type="button"
        onClick={() => imgUrl && onOpen()}
        disabled={!imgUrl}
        aria-label={`Enlarge ${candidate.role}`}
        className="group relative w-full aspect-[3/4] bg-app flex items-center justify-center disabled:cursor-default"
      >
        {imgUrl ? (
          <>
            <img src={imgUrl} alt={candidate.role} className="w-full h-full object-cover" />
            {/* Enlarge affordance — visible on hover/focus, always tappable on touch. */}
            <span className="absolute top-2 right-2 rounded-md bg-black/60 p-1.5 text-ink opacity-100 sm:opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 transition-opacity">
              <Maximize2 className="w-4 h-4" />
            </span>
          </>
        ) : imgError ? (
          <div className="flex flex-col items-center gap-1 text-ink-3 text-xs">
            <ImageIcon className="w-5 h-5" /> no image
          </div>
        ) : (
          <Loader2 className="w-5 h-5 text-ink-3 animate-spin" />
        )}
      </button>

      <div className="p-3 space-y-2 flex-1 flex flex-col">
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-xs text-ink truncate" title={candidate.role}>{candidate.role}</span>
          <StatusBadge status={candidate.status} />
        </div>
        {candidate.caption && (
          <p className="text-[11px] leading-snug text-ink-3 line-clamp-3">{candidate.caption}</p>
        )}

        <div className="mt-auto pt-1 flex items-center gap-2">
          {isFailed ? (
            <span className="text-[11px] text-amber-400/80">{candidate.error || 'generation failed'}</span>
          ) : candidate.status === 'pending_review' ? (
            <>
              <button
                type="button"
                onClick={() => click('approved')}
                disabled={busy}
                className="btn btn-secondary text-xs flex-1 flex items-center justify-center gap-1 disabled:opacity-50"
              >
                <CheckCircle2 className="w-3.5 h-3.5" /> Approve
              </button>
              <button
                type="button"
                onClick={() => click('rejected')}
                disabled={busy}
                className="btn btn-secondary text-xs flex-1 flex items-center justify-center gap-1 disabled:opacity-50"
              >
                <XCircle className="w-3.5 h-3.5" /> Reject
              </button>
            </>
          ) : (
            <>
              {candidate.status === 'approved' ? (
                <button
                  type="button"
                  onClick={() => click('rejected')}
                  disabled={busy}
                  className="btn btn-secondary text-xs flex-1 flex items-center justify-center gap-1 disabled:opacity-50"
                >
                  <XCircle className="w-3.5 h-3.5" /> Reject
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => click('approved')}
                  disabled={busy}
                  className="btn btn-secondary text-xs flex-1 flex items-center justify-center gap-1 disabled:opacity-50"
                >
                  <CheckCircle2 className="w-3.5 h-3.5" /> Approve
                </button>
              )}
              <button
                type="button"
                onClick={() => click('pending_review')}
                disabled={busy}
                title="Reset to pending"
                className="btn btn-secondary text-xs flex items-center justify-center gap-1 disabled:opacity-50"
              >
                <RotateCcw className="w-3.5 h-3.5" />
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Full-size lightbox for a single candidate (S24W.1). Closes on Esc and backdrop
 * click; approve/reject persist via the same review handler as the grid, and the
 * shown status reflects the live candidate the parent passes in.
 */
function CandidateModal({
  characterId,
  candidate,
  onReview,
  onClose,
}: {
  characterId: number;
  candidate: TrainingCandidate;
  onReview: (role: string, status: TrainingCandidateStatus) => Promise<void>;
  onClose: () => void;
}) {
  const { imgUrl, imgError } = useCandidateImage(characterId, candidate.role);
  const [busy, setBusy] = useState(false);

  // Esc to close.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const click = async (status: TrainingCandidateStatus) => {
    setBusy(true);
    try {
      await onReview(candidate.role, status);
    } finally {
      setBusy(false);
    }
  };

  const isFailed = candidate.status === 'failed';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`Candidate ${candidate.role}`}
    >
      <div
        className="relative w-full max-w-3xl max-h-[92vh] overflow-y-auto rounded-xl border border-edge bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute top-2 right-2 z-10 rounded-md bg-black/60 p-1.5 text-ink hover:text-white hover:bg-black/80 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="p-4 space-y-3">
          {/* Image — fits the viewport, never cropped. */}
          <div className="flex items-center justify-center rounded-lg bg-app min-h-[12rem]">
            {imgUrl ? (
              <img src={imgUrl} alt={candidate.role} className="max-h-[70vh] w-auto max-w-full object-contain" />
            ) : imgError ? (
              <div className="flex flex-col items-center gap-1 text-ink-3 text-sm py-12">
                <ImageIcon className="w-6 h-6" /> no image
              </div>
            ) : (
              <Loader2 className="w-6 h-6 text-ink-3 animate-spin my-12" />
            )}
          </div>

          <div className="flex items-center justify-between gap-2">
            <span className="font-mono text-sm text-ink break-all">{candidate.role}</span>
            <StatusBadge status={candidate.status} />
          </div>
          {candidate.caption && (
            <p className="text-xs leading-relaxed text-ink-2">{candidate.caption}</p>
          )}

          {isFailed ? (
            <p className="text-xs text-amber-400/80">{candidate.error || 'generation failed'}</p>
          ) : (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <button
                type="button"
                onClick={() => click('approved')}
                disabled={busy || candidate.status === 'approved'}
                className="btn btn-secondary text-sm flex items-center justify-center gap-1.5 disabled:opacity-50"
              >
                <CheckCircle2 className="w-4 h-4" /> Approve
              </button>
              <button
                type="button"
                onClick={() => click('rejected')}
                disabled={busy || candidate.status === 'rejected'}
                className="btn btn-secondary text-sm flex items-center justify-center gap-1.5 disabled:opacity-50"
              >
                <XCircle className="w-4 h-4" /> Reject
              </button>
              {candidate.status !== 'pending_review' && (
                <button
                  type="button"
                  onClick={() => click('pending_review')}
                  disabled={busy}
                  title="Reset to pending"
                  className="btn btn-secondary text-sm flex items-center justify-center gap-1.5 disabled:opacity-50"
                >
                  <RotateCcw className="w-4 h-4" /> Reset
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function TrainingPackReview({ characterId }: { characterId: number }) {
  const [data, setData] = useState<TrainingPackReviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeRole, setActiveRole] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    setLoading(true);
    setError('');
    apiClient
      .getTrainingCandidates(characterId)
      .then((d) => { if (mountedRef.current) setData(d); })
      .catch((e) => { if (mountedRef.current) setError(e instanceof Error ? e.message : 'Failed to load candidates'); })
      .finally(() => { if (mountedRef.current) setLoading(false); });
  }, [characterId]);

  // Persist a decision, then update the single card + recompute counts locally.
  const handleReview = async (role: string, status: TrainingCandidateStatus) => {
    const updated = await apiClient.reviewTrainingCandidate(characterId, role, status);
    if (!mountedRef.current) return;
    setData((prev) => {
      if (!prev) return prev;
      const candidates = prev.candidates.map((c) => (c.role === role ? { ...c, ...updated } : c));
      const counts: Record<string, number> = {
        total_roles: candidates.length,
        pending_review: candidates.filter((c) => c.status === 'pending_review').length,
        approved: candidates.filter((c) => c.status === 'approved').length,
        rejected: candidates.filter((c) => c.status === 'rejected').length,
        failed: candidates.filter((c) => c.status === 'failed').length,
      };
      const review_state = counts.pending_review === 0 ? 'review_complete' : 'candidates_pending_review';
      return { ...prev, candidates, counts, review_state };
    });
  };

  if (loading) return <p className="text-sm text-ink-3">Loading training candidates…</p>;
  if (error) {
    return (
      <p className="text-sm text-amber-400 bg-amber-950/40 border border-amber-800/40 rounded-lg px-4 py-2">
        {error}
      </p>
    );
  }
  if (!data || data.candidates.length === 0) {
    return <p className="text-sm text-ink-3">No training-pack candidates have been staged yet.</p>;
  }

  const c = data.counts;
  // Live candidate for the open lightbox so its status/buttons stay in sync.
  const activeCandidate = activeRole ? data.candidates.find((x) => x.role === activeRole) ?? null : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
        <span className="text-ink-2">{c.total_roles ?? data.candidates.length} candidates</span>
        <span>·</span>
        <span className="text-gem">{c.approved ?? 0} approved</span>
        <span className="text-red-300">{c.rejected ?? 0} rejected</span>
        <span className="text-ink-2">{c.pending_review ?? 0} pending</span>
        {(c.failed ?? 0) > 0 && <span className="text-amber-300">{c.failed} failed</span>}
      </div>

      <p className="text-xs text-ink-3 bg-surface border border-edge rounded-lg px-3 py-2">
        Decisions are saved to the candidate pack manifest. No training runs and no final
        pack is exported here — that stays a separate, explicit step.
      </p>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {data.candidates.map((cand) => (
          <CandidateCard
            key={cand.role}
            characterId={characterId}
            candidate={cand}
            onReview={handleReview}
            onOpen={() => setActiveRole(cand.role)}
          />
        ))}
      </div>

      {activeCandidate && (
        <CandidateModal
          characterId={characterId}
          candidate={activeCandidate}
          onReview={handleReview}
          onClose={() => setActiveRole(null)}
        />
      )}
    </div>
  );
}
