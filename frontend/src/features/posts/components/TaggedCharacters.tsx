/**
 * TaggedCharacters — the post's secondary identity line (W-10A).
 *
 * Renders, beneath the author row of a post header:
 *
 *     Featuring Kiera Fielding, Grace Fielding +2 · in The Commons
 *
 * "Featuring" is the user-facing word for an explicit tag (internally still
 * `tagged_characters` / `post_character_tags`). It is deliberately NOT
 * authorship: it never appears in the byline, never says "with", and sits in
 * the quieter metadata line so the author stays visually dominant.
 *
 * The same line carries the post's existing context (realm, etc.) passed in as
 * `context`, so a header has ONE secondary line rather than metadata scattered
 * above and below the body. With no featured characters it renders just the
 * context, exactly as before; with neither it renders nothing.
 *
 * More than three featured characters collapse to the first two plus "+N",
 * which expands in place. When `removableCharacterId` names one of them (the
 * viewer owns that character, on its Featured tab) it is always listed first,
 * and a small "Remove from Featured" action follows, confirmed through
 * ConfirmDialog.
 *
 * The list is already filtered for the viewer by the server; this component
 * renders what it is given.
 */
import { Fragment, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import ConfirmDialog from '@/components/ConfirmDialog';
import type { TaggedCharacter } from '@/lib/types';

/** Up to this many are always shown in full; beyond it, the line collapses. */
export const FEATURING_FULL_LIST_MAX = 3;
/** How many names stay visible when collapsed. */
export const FEATURING_COLLAPSED_VISIBLE = 2;

interface Props {
  postId: number;
  tags?: TaggedCharacter[] | null;
  /** The post's existing context (e.g. "in The Commons"), shown after a dot. */
  context?: ReactNode;
  /** The one featured character whose association the viewer may remove here. */
  removableCharacterId?: number | null;
  onRemoved?: (characterId: number) => void;
  className?: string;
}

const nameLinkCls =
  'font-medium text-ink-2 hover:text-gem transition-colors rounded-sm break-words ' +
  'focus:outline-none focus-visible:ring-2 focus-visible:ring-gem/60';

export default function TaggedCharacters({
  postId,
  tags,
  context,
  removableCharacterId = null,
  onRemoved,
  className = '',
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const [confirming, setConfirming] = useState<TaggedCharacter | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const list = tags ?? [];
  const hasContext = context !== undefined && context !== null && context !== false;
  if (list.length === 0 && !hasContext) return null;

  // The viewer's own (removable) character leads, so it is never collapsed away.
  const ordered = removableCharacterId == null
    ? list
    : [
        ...list.filter((t) => t.character_id === removableCharacterId),
        ...list.filter((t) => t.character_id !== removableCharacterId),
      ];
  const collapsible = ordered.length > FEATURING_FULL_LIST_MAX;
  const visible = collapsible && !expanded ? ordered.slice(0, FEATURING_COLLAPSED_VISIBLE) : ordered;
  const hidden = ordered.slice(visible.length);
  const removable = onRemoved ? ordered.find((t) => t.character_id === removableCharacterId) ?? null : null;

  const remove = async () => {
    if (!confirming) return;
    setBusy(true);
    setError(null);
    try {
      await apiClient.removePostTag(postId, confirming.character_id);
      const removed = confirming.character_id;
      setConfirming(null);
      onRemoved?.(removed);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove this character from Featured.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div
        className={`flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5 min-w-0 ${className}`}
        data-testid="post-context-line"
      >
        {ordered.length > 0 && (
          <span className="text-xs text-ink-3 min-w-0" data-testid="tagged-characters">
            Featuring{' '}
            {visible.map((t, i) => (
              <Fragment key={t.character_id}>
                {i > 0 && ', '}
                <Link
                  to={`/characters/${t.character_id}`}
                  className={nameLinkCls}
                  onClick={(e) => e.stopPropagation()}
                >
                  {t.name}
                </Link>
              </Fragment>
            ))}
            {hidden.length > 0 && (
              <>
                {' '}
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setExpanded(true); }}
                  aria-expanded={false}
                  aria-label={`Show ${hidden.length} more featured: ${hidden.map((t) => t.name).join(', ')}`}
                  className="font-medium text-ink-2 hover:text-gem transition-colors rounded-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-gem/60"
                >
                  +{hidden.length}
                </button>
              </>
            )}
          </span>
        )}
        {ordered.length > 0 && hasContext && (
          <span aria-hidden="true" className="text-[11px] text-ink-3/70">·</span>
        )}
        {hasContext && context}
        {removable && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setError(null); setConfirming(removable); }}
            aria-label={`Remove ${removable.name} from Featured on this post`}
            className="ml-1 px-1.5 py-px rounded-md border border-edge-md text-[11px] font-medium text-ink-2 hover:text-ink hover:border-ink-3 hover:bg-surface-elevated transition-colors focus:outline-none focus-visible:text-ink focus-visible:ring-2 focus-visible:ring-gem/60"
          >
            Remove from Featured
          </button>
        )}
      </div>

      <ConfirmDialog
        open={confirming !== null}
        title="Remove from Featured?"
        confirmLabel="Remove from Featured"
        danger
        busy={busy}
        error={error}
        onConfirm={remove}
        onCancel={() => { setConfirming(null); setError(null); }}
      >
        <p>
          {confirming?.name} will no longer be featured on this post. The original post is not
          deleted or edited — only this association is removed.
        </p>
      </ConfirmDialog>
    </>
  );
}
