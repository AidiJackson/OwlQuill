import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { Character, Post, Realm } from '@/lib/types';
import { authorLink } from '@/lib/authorLink';
import InlineNotice from '@/components/InlineNotice';
import MentionText from '@/components/MentionText';
import TaggedCharacters from '@/features/posts/components/TaggedCharacters';
import { PostKindBadge, PostTypeBadge } from '@/components/PostBadges';
import ProvenanceBadge from '@/components/ProvenanceBadge';
import ReactionBar from '@/components/ReactionBar';
import CommentSection from '@/components/CommentSection';
import PostMenu from '@/components/PostMenu';
import { useAuthStore } from '@/lib/store';

/**
 * One post, at its own address — Polish Phase 7.1.
 *
 * The destination a notification lands on. Until now a mention could only
 * send the reader to the feed root and hope the post was near the top; this
 * page asks ``GET /posts/{id}`` for exactly that post. The server decides
 * whether the reader may have it (realm visibility, unchanged), so a private
 * post, a deleted post and a made-up id all arrive here as the same 404 and
 * are told apart from nothing: the page says the post is not available and
 * offers the way back. Nothing cached elsewhere — a notification's preview,
 * say — is ever shown in its place.
 *
 * Deliberately a compact single-post card, not a copy of the feed: the same
 * identity header, body, reactions and comments the feed renders, built from
 * the same components, minus feed-only affordances (composer,
 * request-to-join). The author's delete menu IS here (W-07A): a post reached
 * from a notification must be removable where it was found. Comments are open
 * by default because that is what a reader who followed a notification came
 * to do — and it is the surface 7.2 comment notifications will land on.
 */
export default function PostDetail() {
  const { postId } = useParams<{ postId: string }>();
  const id = Number(postId);

  const [post, setPost] = useState<Post | null>(null);
  const [realm, setRealm] = useState<Realm | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [deleted, setDeleted] = useState(false);
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    if (!Number.isInteger(id) || id <= 0) {
      setUnavailable(true);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setUnavailable(false);
    setLoadError(null);
    setDeleted(false);

    apiClient
      .getPost(id)
      .then((p) => {
        if (cancelled) return;
        setPost(p);
        // The realm name is context, not content: if it cannot be fetched the
        // post still renders. The comment composer wants the reader's own
        // characters; a Wanderer simply has none.
        if (p.realm_id) {
          apiClient.getRealm(p.realm_id).then((r) => { if (!cancelled) setRealm(r); }).catch(() => undefined);
        }
        apiClient.getCharacters().then((cs) => { if (!cancelled) setCharacters(cs); }).catch(() => undefined);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // The post route answers "Post not found" for a missing post AND for
        // one in a private realm the reader is not part of — on purpose, so
        // existence is not probeable. Both are "not available" here.
        const message = err instanceof Error ? err.message : '';
        if (/not found/i.test(message)) setUnavailable(true);
        else setLoadError("Couldn't load this post.");
      })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [id]);

  if (loading) {
    return (
      <div className="flex justify-center py-16" role="status" aria-label="Loading post">
        <div className="w-8 h-8 border-4 border-gem/25 border-t-gem rounded-full animate-spin" />
      </div>
    );
  }

  if (deleted) {
    return (
      <div className="max-w-2xl mx-auto px-5 sm:px-8 py-10">
        <InlineNotice tone="info">
          <p className="font-medium">Post deleted.</p>
        </InlineNotice>
        <div className="mt-6 flex flex-wrap gap-4 text-sm">
          {realm && (
            <Link to={`/realms/${realm.id}`} className="text-gem hover:opacity-80">Back to {realm.name}</Link>
          )}
          <Link to="/" className="text-gem hover:opacity-80">Go to the Commons</Link>
        </div>
      </div>
    );
  }

  if (unavailable || loadError || !post) {
    return (
      <div className="max-w-2xl mx-auto px-5 sm:px-8 py-10">
        <InlineNotice tone={unavailable ? 'info' : 'error'}>
          <p className="font-medium">
            {unavailable ? "This post isn't available." : loadError}
          </p>
          {unavailable && (
            <p className="mt-1 text-ink-3">
              It may have been removed, or it lives in a private Realm you're not part of.
            </p>
          )}
        </InlineNotice>
        <div className="mt-6 flex flex-wrap gap-4 text-sm">
          <Link to="/notifications" className="text-gem hover:opacity-80">Back to notifications</Link>
          <Link to="/" className="text-gem hover:opacity-80">Go to the Commons</Link>
        </div>
      </div>
    );
  }

  const author = authorLink(post);
  const headerHref = author.href ?? '#';

  return (
    <div className="max-w-2xl mx-auto px-5 sm:px-8 py-10">
      <nav aria-label="Breadcrumb" className="mb-6 text-[11px] font-mono text-ink-3 flex flex-wrap gap-1">
        {realm ? (
          <Link to={`/realms/${realm.id}`} className="hover:text-gem transition-colors">{realm.name}</Link>
        ) : (
          <Link to="/" className="hover:text-gem transition-colors">Commons</Link>
        )}
        <span aria-hidden="true">/</span>
        <span className="text-ink-2">Post</span>
      </nav>

      <article className="py-2">
        <header className="flex items-start justify-between mb-4 gap-2">
          <div className="flex items-start gap-3 min-w-0 flex-1">
            {post.character_name ? (
              <Link to={headerHref} className="flex-shrink-0 mt-0.5">
                {post.character_avatar_url ? (
                  <img
                    src={post.character_avatar_url}
                    alt={post.character_name}
                    className="w-9 h-9 rounded-full object-cover border border-edge-md"
                  />
                ) : (
                  <div className="w-9 h-9 rounded-full bg-gem-soft border border-gem/20 flex items-center justify-center text-sm font-semibold text-gem">
                    {post.character_name.charAt(0)}
                  </div>
                )}
              </Link>
            ) : (
              <div className="flex-shrink-0 mt-0.5">
                {author.avatarUrl ? (
                  <img src={author.avatarUrl} alt={author.label} className="w-9 h-9 rounded-full object-cover border border-edge" />
                ) : (
                  <div className="w-9 h-9 rounded-full bg-surface-elevated border border-edge flex items-center justify-center text-sm font-medium text-ink-3">
                    ✦
                  </div>
                )}
              </div>
            )}

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-1.5">
                {post.character_name ? (
                  <Link to={headerHref} className="text-sm font-semibold text-ink hover:text-gem transition-colors leading-tight truncate max-w-full">
                    {post.character_name}
                  </Link>
                ) : (
                  <span className="text-sm font-medium text-ink-2">{author.label}</span>
                )}
                <PostTypeBadge contentType={post.content_type} />
                <PostKindBadge postKind={post.post_kind} />
                <ProvenanceBadge provenance={post.provenance} />
              </div>
              {realm && (
                <div className="mt-0.5 text-[11px] font-mono text-ink-3">
                  in <span className={realm.is_commons ? 'text-ink-3' : 'text-gem/80'}>{realm.name}</span>
                </div>
              )}
            </div>
          </div>
          <div className="flex items-center gap-1.5 flex-shrink-0 mt-0.5">
            <time
              dateTime={post.created_at}
              className="text-[11px] font-mono text-ink-3"
            >
              {new Date(post.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
            </time>
            {user && (post.author_user_id === user.id || user.is_admin) && (
              <PostMenu postId={post.id} commentCount={post.comment_count} onDeleted={() => setDeleted(true)} />
            )}
          </div>
        </header>

        {post.title && <h1 className="fic-title text-[21px] font-medium mb-2">{post.title}</h1>}
        <p
          className={`fic-read whitespace-pre-wrap ${
            post.content_type === 'ooc' ? 'fic-ooc' : post.content_type === 'narration' ? 'fic-narration' : ''
          }`}
        >
          <MentionText text={post.content} mentions={post.mentions} />
        </p>

        <TaggedCharacters postId={post.id} tags={post.tagged_characters} className="mt-3" />

        {post.image_url && (
          <img
            src={post.image_url}
            alt={post.title || 'Post image'}
            className="mt-4 rounded-xl border border-edge max-h-[32rem] object-contain"
            loading="lazy"
            decoding="async"
          />
        )}

        <ReactionBar postId={post.id} />
        <CommentSection
          postId={post.id}
          characters={characters}
          defaultExpanded
          commentCount={post.comment_count}
          onCommentCountChange={(d) => setPost((p) => (p ? { ...p, comment_count: Math.max(0, (p.comment_count ?? 0) + d) } : p))}
        />
      </article>
    </div>
  );
}
