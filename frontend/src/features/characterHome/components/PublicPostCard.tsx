import type { CharacterHomePostPublic } from '@/lib/types';
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
    </article>
  );
}
