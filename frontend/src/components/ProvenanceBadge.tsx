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
 * - **Created elsewhere** — everything else. This is a statement about *where
 *   the content was created*, not an accusation. Notepad, Word, Docs, Discord,
 *   an imported roleplay log, a translation, an archived post and an outside AI
 *   all land here alike, because we genuinely cannot tell them apart and will
 *   not pretend otherwise. "Created" rather than "written" because much of what
 *   arrives this way was collaborative, chatted, logged or converted rather than
 *   authored in one sitting.
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
/** Exported so the tests assert against *this* table rather than a copy of it. */
export const BADGES: Record<
  string,
  { icon: string; label: string; className: string; title: string }
> = {
  user_written: {
    icon: '✍️',
    label: 'Written in Ficshon',
    className: 'badge-written',
    title: 'Ficshon watched this being composed here.',
  },
  ai_assisted: {
    icon: '✨',
    label: 'AI Assisted',
    className: 'badge-ai',
    title: "Produced or substantially assisted by Ficshon's own AI tools.",
  },
  external: {
    icon: '📄',
    label: 'Created elsewhere',
    className: 'badge-external',
    title: 'Not composed in Ficshon. This is not a claim about AI.',
  },
  // Legacy. Rows created before the provenance system carry `unknown` and were
  // deliberately never backfilled, so the database still distinguishes "never
  // evaluated" from "evaluated, not composed here". Publicly they say the same
  // thing: Ficshon did not observe this being created here.
  unknown: {
    icon: '📄',
    label: 'Created elsewhere',
    className: 'badge-external',
    title: 'Not composed in Ficshon. This is not a claim about AI.',
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
      // Geometry from the shared `.badge` rule, so this sits at exactly the
      // height of the IC/OOC chip beside it — see index.css and PostBadges.
      className={`badge ${badge.className} ${className}`}
      title={badge.title}
    >
      {/* Decoration only. Read aloud, "writing hand Written in Ficshon" is
          noise; the label alone says the whole thing. */}
      <span aria-hidden="true">{badge.icon}</span>
      {badge.label}
    </span>
  );
}
