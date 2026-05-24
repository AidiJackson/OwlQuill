import { useState, useEffect, useCallback } from 'react';
import { Image, Lock, RefreshCw, AlertCircle, CheckCircle2, Loader2, ChevronDown, ChevronRight } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { BodyMarkingRead, MarkingAnchorStatus } from '@/lib/types';

interface Props {
  characterId: number;
  isOwner: boolean;
}

const PLACEMENT_LABELS: Record<string, string> = {
  left_upper_arm: 'Left Upper Arm',
  left_forearm: 'Left Forearm',
  left_full_arm: 'Left Arm (Sleeve)',
  right_upper_arm: 'Right Upper Arm',
  right_forearm: 'Right Forearm',
  right_full_arm: 'Right Arm (Sleeve)',
  chest: 'Chest',
  upper_back: 'Upper Back',
  lower_back: 'Lower Back',
  full_back: 'Full Back',
  side: 'Side',
  ribs: 'Ribs',
  abdomen: 'Abdomen',
  neck: 'Neck',
  throat: 'Throat',
  right_cheek: 'Right Cheek',
  left_cheek: 'Left Cheek',
  forehead: 'Forehead',
  chin: 'Chin',
  jaw: 'Jaw',
  left_hand: 'Left Hand',
  right_hand: 'Right Hand',
  knuckles: 'Knuckles',
  left_thigh: 'Left Thigh',
  right_thigh: 'Right Thigh',
  left_calf: 'Left Calf',
  right_calf: 'Right Calf',
};

const TYPE_LABELS: Record<string, string> = {
  tattoo: 'Tattoo',
  scar: 'Scar',
  burn: 'Burn',
  birthmark: 'Birthmark',
};

function AnchorStatusBadge({ status }: { status: MarkingAnchorStatus }) {
  if (status === 'locked') {
    return (
      <span className="flex items-center gap-1 text-xs text-green-400">
        <CheckCircle2 className="w-3 h-3" />
        Locked
      </span>
    );
  }
  if (status === 'generated') {
    return (
      <span className="flex items-center gap-1 text-xs text-yellow-400">
        <AlertCircle className="w-3 h-3" />
        Generated — not locked
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-xs text-zinc-500">
      <AlertCircle className="w-3 h-3" />
      No anchor — consistency may vary
    </span>
  );
}

interface MarkingCardProps {
  characterId: number;
  marking: BodyMarkingRead;
  onUpdate: (updated: BodyMarkingRead) => void;
}

function MarkingCard({ characterId, marking, onUpdate }: MarkingCardProps) {
  const [busy, setBusy] = useState<'generate' | 'lock' | 'replace' | null>(null);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(false);

  async function handleGenerate() {
    setBusy('generate');
    setError('');
    try {
      const resp = await apiClient.generateBodyAnchor(characterId, marking.id);
      onUpdate(resp.marking);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Generation failed');
    } finally {
      setBusy(null);
    }
  }

  async function handleLock() {
    setBusy('lock');
    setError('');
    try {
      const resp = await apiClient.lockBodyAnchor(characterId, marking.id);
      onUpdate(resp.marking);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Lock failed');
    } finally {
      setBusy(null);
    }
  }

  async function handleReplace() {
    setBusy('replace');
    setError('');
    try {
      const resp = await apiClient.replaceBodyAnchor(characterId, marking.id);
      onUpdate(resp.marking);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Replace failed');
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="border border-zinc-700 rounded-lg bg-zinc-800/50 overflow-hidden">
      {/* Card header */}
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center justify-between p-3 text-left hover:bg-zinc-700/30 transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs font-medium text-zinc-300 bg-zinc-700 px-2 py-0.5 rounded shrink-0">
            {TYPE_LABELS[marking.type] ?? marking.type}
          </span>
          <span className="text-sm font-medium text-white truncate">
            {PLACEMENT_LABELS[marking.placement] ?? marking.placement}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <AnchorStatusBadge status={marking.anchor_status} />
          {expanded ? (
            <ChevronDown className="w-4 h-4 text-zinc-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-zinc-500" />
          )}
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-3 border-t border-zinc-700/50">
          {/* Description */}
          <p className="text-xs text-zinc-400 pt-2">{marking.style}</p>

          {/* Anchor image */}
          {marking.anchor_image_url && (
            <div className="rounded overflow-hidden border border-zinc-700 bg-zinc-900">
              <img
                src={marking.anchor_image_url}
                alt={`${PLACEMENT_LABELS[marking.placement]} anchor`}
                className="w-full max-h-48 object-contain"
              />
            </div>
          )}

          {/* Actions */}
          <div className="flex flex-wrap gap-2">
            {marking.anchor_status === 'missing' && (
              <button
                onClick={handleGenerate}
                disabled={!!busy}
                className="flex items-center gap-1.5 text-xs btn btn-primary"
              >
                {busy === 'generate' ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Image className="w-3 h-3" />
                )}
                Generate Anchor
              </button>
            )}

            {marking.anchor_status === 'generated' && (
              <>
                <button
                  onClick={handleLock}
                  disabled={!!busy}
                  className="flex items-center gap-1.5 text-xs btn btn-primary"
                >
                  {busy === 'lock' ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <Lock className="w-3 h-3" />
                  )}
                  Lock Anchor
                </button>
                <button
                  onClick={handleReplace}
                  disabled={!!busy}
                  className="flex items-center gap-1.5 text-xs btn btn-secondary"
                >
                  {busy === 'replace' ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <RefreshCw className="w-3 h-3" />
                  )}
                  Regenerate
                </button>
              </>
            )}

            {marking.anchor_status === 'locked' && (
              <button
                onClick={handleReplace}
                disabled={!!busy}
                className="flex items-center gap-1.5 text-xs btn btn-secondary"
              >
                {busy === 'replace' ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <RefreshCw className="w-3 h-3" />
                )}
                Replace Anchor
              </button>
            )}
          </div>

          {error && (
            <p className="text-xs text-red-400">{error}</p>
          )}
        </div>
      )}
    </div>
  );
}

export default function BodyCanonPanel({ characterId, isOwner }: Props) {
  const [markings, setMarkings] = useState<BodyMarkingRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadMarkings = useCallback(async () => {
    if (!isOwner) return;
    setLoading(true);
    setError('');
    try {
      const data = await apiClient.getBodyMarkings(characterId);
      setMarkings(data.markings);
    } catch {
      setError('Could not load body canon markings.');
    } finally {
      setLoading(false);
    }
  }, [characterId, isOwner]);

  useEffect(() => {
    loadMarkings();
  }, [loadMarkings]);

  function handleMarkingUpdate(updated: BodyMarkingRead) {
    setMarkings(prev => prev.map(m => m.id === updated.id ? updated : m));
  }

  if (!isOwner) return null;

  const tattoos = markings.filter(m => m.type === 'tattoo');
  const other = markings.filter(m => m.type !== 'tattoo');

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">Body Canon</h3>
        <span className="text-xs text-zinc-500">Locked anatomical truth</span>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <Loader2 className="w-3 h-3 animate-spin" />
          Loading markings…
        </div>
      )}

      {error && (
        <p className="text-xs text-red-400">{error}</p>
      )}

      {!loading && markings.length === 0 && (
        <p className="text-xs text-zinc-500">
          No body canon markings. Apply tattoo presets from Style Shops to create them.
        </p>
      )}

      {tattoos.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-zinc-400 uppercase tracking-wide">Tattoos</p>
          {tattoos.map(m => (
            <MarkingCard
              key={m.id}
              characterId={characterId}
              marking={m}
              onUpdate={handleMarkingUpdate}
            />
          ))}
        </div>
      )}

      {other.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-zinc-400 uppercase tracking-wide">Scars & Marks</p>
          {other.map(m => (
            <MarkingCard
              key={m.id}
              characterId={characterId}
              marking={m}
              onUpdate={handleMarkingUpdate}
            />
          ))}
        </div>
      )}
    </div>
  );
}
