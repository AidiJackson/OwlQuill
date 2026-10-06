/**
 * TaggedCharacters — the "Tagged: …" line on a post (W-10A).
 *
 * Shared by every post card so tags render one way everywhere, and always
 * SEPARATELY from the author byline. The wording is deliberately neutral —
 * "Tagged:", never "with" — because a tag is the author's association, not a
 * claim that the tagged character took part.
 *
 * The list is already filtered for the viewer by the server; this component
 * renders what it is given. When `removableCharacterId` names one of the tags
 * (the viewer owns that character, on its Tagged surface), a small "Remove
 * tag" action appears beside it, confirmed through ConfirmDialog.
 */
import { Fragment, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import ConfirmDialog from '@/components/ConfirmDialog';
import type { TaggedCharacter } from '@/lib/types';

interface Props {
  postId: number;
  tags?: TaggedCharacter[] | null;
  /** The one tagged character whose tag the viewer may remove here. */
  removableCharacterId?: number | null;
  onRemoved?: (characterId: number) => void;
  className?: string;
}

export default function TaggedCharacters({ postId, tags, removableCharacterId = null, onRemoved, className = '' }: Props) {
  const [confirming, setConfirming] = useState<TaggedCharacter | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!tags || tags.length === 0) return null;

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
      setError(err instanceof Error ? err.message : 'Could not remove the tag.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <p className={`text-xs text-ink-3 ${className}`} data-testid="tagged-characters">
        <span className="font-medium text-ink-2">Tagged: </span>
        {tags.map((t, i) => (
          <Fragment key={t.character_id}>
            {i > 0 && ', '}
            <Link
              to={`/characters/${t.character_id}`}
              className="text-gem hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              {t.name}
            </Link>
            {onRemoved && removableCharacterId === t.character_id && (
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setError(null); setConfirming(t); }}
                className="ml-1.5 text-[11px] text-ink-3 underline hover:text-ink transition-colors"
                aria-label={`Remove tag of ${t.name} from this post`}
              >
                Remove tag
              </button>
            )}
          </Fragment>
        ))}
      </p>

      <ConfirmDialog
        open={confirming !== null}
        title="Remove tag?"
        confirmLabel="Remove tag"
        danger
        busy={busy}
        error={error}
        onConfirm={remove}
        onCancel={() => { setConfirming(null); setError(null); }}
      >
        <p>
          {confirming?.name} will no longer be tagged on this post. The post itself is not changed,
          and the tag can't be added back by you.
        </p>
      </ConfirmDialog>
    </>
  );
}
