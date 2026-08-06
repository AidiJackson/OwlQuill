import type { Provenance } from '@/lib/types';

/**
 * The authorship badge. One component, one vocabulary — it previously existed
 * as three drifting copies in Home, RealmDetail and the Story Space PostList.
 *
 * Two rules make this honest:
 *
 * 1. **No default.** An unrecognised or unknown state renders nothing. The old
 *    badge coalesced `null` to "User Written", so every historical post and
 *    every seeded post claimed authorship nobody had evidence for. A missing
 *    badge is the correct output when the server has nothing to assert.
 *
 * 2. **Unrecognised states are safe.** The server may introduce a verdict (an
 *    `external` / `imported` state is planned) before the client knows it.
 *    Falling through to no badge means a new state can ship server-side without
 *    ever mislabelling a post here.
 */
const BADGES: Record<string, { label: string; className: string }> = {
  user_written: {
    label: '✍️ Written in Ficshon',
    className: 'text-ink-2/80 border-edge-md bg-surface-elevated',
  },
  ai_assisted: {
    label: '✨ AI Assisted',
    className: 'text-purple-400/80 border-purple-800/50 bg-purple-950/30',
  },
};

export default function ProvenanceBadge({
  provenance,
  className = '',
}: {
  provenance?: Provenance | null;
  className?: string;
}) {
  const badge = provenance ? BADGES[provenance] : undefined;
  if (!badge) return null;

  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded border select-none ${badge.className} ${className}`}
    >
      {badge.label}
    </span>
  );
}
