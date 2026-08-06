import type { Provenance } from '@/lib/types';

/**
 * The authorship badge. One component, one vocabulary — it previously existed
 * as three drifting copies in Home, RealmDetail and the Story Space PostList.
 *
 * Three states, and the philosophy behind them is that Ficshon states what it
 * knows rather than guessing what it does not:
 *
 * - **Written in Ficshon** — we watched it being composed here.
 * - **AI Assisted** — our own AI tools produced or substantially assisted it.
 * - **Written elsewhere** — everything else. This is a statement about *where
 *   composition happened*, not an accusation. Notepad, Word, Docs, Discord, an
 *   old RP site and an outside AI all land here alike, because we genuinely
 *   cannot tell them apart and will not pretend otherwise.
 *
 * Two rules keep it honest:
 *
 * 1. **No default that flatters.** The old badge coalesced `null` to "User
 *    Written", so every historical and seeded post claimed authorship nobody
 *    had evidence for. Nothing here can produce that claim by accident — the
 *    only way to get "Written in Ficshon" is for the server to have said so.
 *
 * 2. **Unrecognised states render nothing.** A verdict the server introduces
 *    before the client knows about it shows no badge rather than a wrong one.
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
  external: {
    label: '📄 Written elsewhere',
    className: 'text-ink-3 border-edge bg-surface',
  },
  // Legacy. Rows created before the provenance system carry `unknown` and were
  // deliberately never backfilled, so the database still distinguishes "never
  // evaluated" from "evaluated, not composed here". Publicly they say the same
  // thing: Ficshon did not observe this being written here.
  unknown: {
    label: '📄 Written elsewhere',
    className: 'text-ink-3 border-edge bg-surface',
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
