import { Link } from 'react-router-dom';
import type {
  CharacterHomeCommentAuthor,
  CharacterHomePostPublic,
  CharacterHomePostSocial,
} from '@/lib/types';
import { resolveImageUrl } from '@/features/characterCreation/shared/api';

/**
 * One post on a public Character Home.
 *
 * A deliberate sibling of the authenticated page's PostCard rather than a
 * reuse of it. Three things differ, and each is the reason:
 *
 * * **Shape.** The public timeline returns flat fields; the internal one
 *   returns a `ProfileTimelineItem` envelope with a `payload`. Bending one into
 *   the other would mean inventing values the server did not send.
 * * **No mention links.** The internal card renders `MentionText`, which emits
 *   `<Link>`s into routes behind `ProtectedRoute` — a logged-out visitor
 *   tapping one would be thrown to `/login` from a page that never asked them
 *   to sign in. The public payload carries no mentions, and this card renders
 *   plain text, so that cannot happen by accident later either.
 * * **No author chrome.** Every post on this page is by this character, whose
 *   name and portrait are already in the hero. Repeating them per post turns a
 *   character's history into a social feed.
 *
 * The realm name IS shown, as unlinked text. It is public context — the post
 * happened somewhere — and the server only ever returns posts from public
 * realms, so it cannot leak a private space.
 *
 * Beneath the post sits its SOCIAL CONTEXT (see PostSocial): the evidence that
 * this character lives among others. It is read-only by construction.
 */
export default function PublicPostCard({ post }: { post: CharacterHomePostPublic }) {
  const date = new Date(post.created_at);
  const dateLabel = Number.isNaN(date.getTime())
    ? null
    : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });

  return (
    <article className="py-6 border-b border-edge last:border-b-0">
      <div className="flex items-center gap-2.5 mb-3 flex-wrap">
        {post.realm_name && (
          <span className="font-mono text-[11px] text-ink-3">in {post.realm_name}</span>
        )}
        {dateLabel && (
          <span className="font-mono text-[11px] text-ink-3 ml-auto">{dateLabel}</span>
        )}
      </div>

      {post.title && <h3 className="fic-title text-lg font-medium mb-1.5">{post.title}</h3>}

      {post.content && <p className="fic-read whitespace-pre-wrap">{post.content}</p>}

      {/* The server has already re-checked this attachment for public-surface
          safety and returned null if it failed, so an image present here is one
          a visitor may see. */}
      {post.image_url && (
        <img
          src={resolveImageUrl(post.image_url)}
          alt={post.title || ''}
          className="mt-4 rounded-xl border border-edge max-h-96 object-contain"
          loading="lazy"
          decoding="async"
        />
      )}

      <PostSocial social={post.social} />
    </article>
  );
}

const REACTIONS = [
  { type: 'heart', emoji: '\u2764\uFE0F', one: 'heart', many: 'hearts' },
  { type: 'star', emoji: '\u2B50', one: 'star', many: 'stars' },
  { type: 'eyes', emoji: '\uD83D\uDC40', one: 'eyes reaction', many: 'eyes reactions' },
] as const;

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * A post's social context on a public Home: reaction totals, the comment
 * count and the latest comments, exactly as the server projected them.
 *
 * READ-ONLY, and visibly so. Totals are plain text with an accessible label —
 * never buttons, never focusable, never hover-styled — because a visitor
 * cannot react, and a control that does nothing (or bounces to a login) is a
 * lie on someone's front door. The authenticated ReactionBar is deliberately
 * not reused.
 *
 * EMPTINESS is omitted: no reactions and no comments renders nothing at all,
 * and a zero total never renders. When there are more comments than the
 * server previewed, the count says so truthfully; there is no "show all",
 * because the Home has no anonymous source for the rest.
 */
function PostSocial({ social }: { social?: CharacterHomePostSocial }) {
  if (!social) return null;
  const totals = REACTIONS.flatMap((r) => {
    const n = social.reactions?.[r.type] ?? 0;
    return n > 0 ? [{ ...r, n }] : [];
  });
  const count = social.comment_count;
  const comments = social.comments ?? [];
  if (totals.length === 0 && count <= 0) return null;

  return (
    <div className="mt-4 pt-3 border-t border-edge" data-testid="post-social">
      <p className="flex items-center gap-3 flex-wrap text-xs text-ink-3 tabular-nums">
        {totals.map((t) => (
          <span key={t.type} aria-label={plural(t.n, t.one, t.many)} className="inline-flex items-center gap-1">
            <span aria-hidden="true">{t.emoji}</span>
            <span aria-hidden="true">{t.n}</span>
          </span>
        ))}
        {totals.length > 0 && count > 0 && <span aria-hidden="true">&middot;</span>}
        {count > 0 && <span>{plural(count, 'comment', 'comments')}</span>}
      </p>

      {comments.length > 0 && (
        <ul className="mt-3 space-y-3">
          {comments.map((c) => (
            <li key={c.id} className="pl-3 border-l-2 border-edge">
              <CommentAuthor author={c.author} />
              <p className="text-sm text-ink-2 whitespace-pre-wrap mt-0.5">{c.content}</p>
            </li>
          ))}
        </ul>
      )}

      {count > comments.length && comments.length > 0 && (
        <p className="mt-3 font-mono text-[11px] text-ink-3">
          Latest {comments.length} of {count} comments shown
        </p>
      )}
    </div>
  );
}

/** Neutral labels for authors the server does not identify. Never an account. */
const NEUTRAL_LABEL: Record<CharacterHomeCommentAuthor['kind'], string> = {
  character: 'A character',
  hidden_character: 'A character',
  wanderer: 'Wanderer',
};

/**
 * Who wrote a comment. Only a character whose own Home is published links, and
 * only to that public Home (`/c/<id>`) — never to `/characters/<id>`, which is
 * the signed-in product behind a guard.
 */
function CommentAuthor({ author }: { author: CharacterHomeCommentAuthor }) {
  const label = (author.kind === 'character' && author.name) || NEUTRAL_LABEL[author.kind];
  const identity = (
    <span className="inline-flex items-center gap-1.5">
      {author.avatar_url ? (
        <img
          src={resolveImageUrl(author.avatar_url)}
          alt=""
          className="w-5 h-5 rounded-full object-cover border border-edge"
          loading="lazy"
          decoding="async"
        />
      ) : (
        <span
          aria-hidden="true"
          className="w-5 h-5 rounded-full bg-surface-elevated border border-edge text-[9px] font-semibold text-ink-3 inline-flex items-center justify-center"
        >
          {label.charAt(0).toUpperCase()}
        </span>
      )}
      <span className="text-sm font-medium text-ink">{label}</span>
    </span>
  );

  if (author.kind === 'character' && author.linkable && author.character_id != null) {
    return (
      <Link to={`/c/${author.character_id}`} className="inline-flex hover:underline underline-offset-2">
        {identity}
      </Link>
    );
  }
  return identity;
}
