import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, XCircle, Clock, AlertTriangle, Loader2, ImageIcon, RotateCcw } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { TrainingPackReview as TrainingPackReviewData, TrainingCandidate, TrainingCandidateStatus } from '@/lib/types';

/**
 * S24W — Adult LoRA v4 Training Pack Review (admin-only, Summer-only).
 *
 * Shows every staged candidate from scripts/summer_lora_v4_pack_candidates/ in a
 * grid; each card has approve / reject controls. Decisions persist into the pack
 * manifest.json (no DB this sprint), so a refresh keeps statuses. This surface
 * never trains, regenerates, or exports a final pack.
 */

const STATUS_META: Record<TrainingCandidateStatus, { label: string; cls: string; Icon: typeof Clock }> = {
  pending_review: { label: 'Pending', cls: 'text-gray-300 border-gray-700 bg-gray-800/50', Icon: Clock },
  approved: { label: 'Approved', cls: 'text-emerald-300 border-emerald-800/50 bg-emerald-900/20', Icon: CheckCircle2 },
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

function CandidateCard({
  characterId,
  candidate,
  onReview,
}: {
  characterId: number;
  candidate: TrainingCandidate;
  onReview: (role: string, status: TrainingCandidateStatus) => Promise<void>;
}) {
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [imgError, setImgError] = useState(false);
  const [busy, setBusy] = useState(false);

  // Blob-load the admin-gated image and revoke the object URL on unmount.
  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    setImgUrl(null);
    setImgError(false);
    apiClient
      .getTrainingCandidateImageUrl(characterId, candidate.role)
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
  }, [characterId, candidate.role]);

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
    <div className="rounded-lg border border-gray-800 bg-gray-900/50 overflow-hidden flex flex-col">
      <div className="aspect-[3/4] bg-gray-950 flex items-center justify-center">
        {imgUrl ? (
          <img src={imgUrl} alt={candidate.role} className="w-full h-full object-cover" />
        ) : imgError ? (
          <div className="flex flex-col items-center gap-1 text-gray-600 text-xs">
            <ImageIcon className="w-5 h-5" /> no image
          </div>
        ) : (
          <Loader2 className="w-5 h-5 text-gray-600 animate-spin" />
        )}
      </div>

      <div className="p-3 space-y-2 flex-1 flex flex-col">
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-xs text-gray-200 truncate" title={candidate.role}>{candidate.role}</span>
          <StatusBadge status={candidate.status} />
        </div>
        {candidate.caption && (
          <p className="text-[11px] leading-snug text-gray-500 line-clamp-3">{candidate.caption}</p>
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

export default function TrainingPackReview({ characterId }: { characterId: number }) {
  const [data, setData] = useState<TrainingPackReviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
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

  if (loading) return <p className="text-sm text-gray-500">Loading training candidates…</p>;
  if (error) {
    return (
      <p className="text-sm text-amber-400 bg-amber-950/40 border border-amber-800/40 rounded-lg px-4 py-2">
        {error}
      </p>
    );
  }
  if (!data || data.candidates.length === 0) {
    return <p className="text-sm text-gray-500">No training-pack candidates have been staged yet.</p>;
  }

  const c = data.counts;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-400">
        <span className="text-gray-300">{c.total_roles ?? data.candidates.length} candidates</span>
        <span>·</span>
        <span className="text-emerald-300">{c.approved ?? 0} approved</span>
        <span className="text-red-300">{c.rejected ?? 0} rejected</span>
        <span className="text-gray-300">{c.pending_review ?? 0} pending</span>
        {(c.failed ?? 0) > 0 && <span className="text-amber-300">{c.failed} failed</span>}
      </div>

      <p className="text-xs text-gray-500 bg-gray-900/50 border border-gray-800 rounded-lg px-3 py-2">
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
          />
        ))}
      </div>
    </div>
  );
}
