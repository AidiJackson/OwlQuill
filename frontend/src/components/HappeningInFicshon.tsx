import { Link } from 'react-router-dom';
import type { Post, Realm } from '@/lib/types';
import { authorLink } from '@/lib/authorLink';

/**
 * "Happening in Ficshon" — a public, character-first activity surface for the
 * Commons right rail. It replaces the old account-management "Your Characters"
 * list so the Commons stays focused on the fictional world rather than the
 * viewer's own account.
 *
 * Data source: the Commons feed the page already loads. This component derives
 * activity from real posts only — it never invents counts, presence, or
 * personalisation. Attribution goes through the canonical character-first
 * `authorLink` helper, so an account username is never shown or linked; a post
 * with no character renders as an unlinked "Wanderer".
 *
 * Failure behaviour: if the feed failed to load, `posts` is empty and the whole
 * panel collapses (renders nothing) — it can never break the Commons.
 *
 * Forward design note: Follow is not yet functional, so this panel is
 * deliberately NOT labelled "Following"/personalised. When a real Follow system
 * lands, swap `heading` to "From Characters You Follow" and pass a
 * follow-scoped feed into `posts` — the item rendering below stays unchanged.
 */

interface Props {
  posts: Post[];
  realms: Realm[];
  /** Loading is quiet + contained; the panel shows a small skeleton, never an error. */
  loading?: boolean;
  limit?: number;
}

function compactTimestamp(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const diffMin = Math.floor((Date.now() - then) / 60_000);
  if (diffMin < 1) return 'now';
  if (diffMin < 60) return `${diffMin}m`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 7) return `${diffDay}d`;
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

const HEADING = 'Happening in Ficshon';

export default function HappeningInFicshon({ posts, realms, loading = false, limit = 6 }: Props) {
  if (loading) {
    return (
      <section aria-label={HEADING}>
        <h3 className="text-[11px] font-mono uppercase tracking-[0.1em] text-ink-3 mb-4">{HEADING}</h3>
        <div className="space-y-3" aria-hidden="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center gap-2.5 animate-pulse">
              <div className="w-8 h-8 rounded-full bg-surface-elevated flex-shrink-0" />
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="h-2.5 rounded bg-surface-elevated w-3/4" />
                <div className="h-2 rounded bg-surface-elevated w-1/2" />
              </div>
            </div>
          ))}
        </div>
      </section>
    );
  }

  const items = posts.slice(0, limit).map((post) => {
    const author = authorLink(post);
    const realm = post.realm_id != null ? realms.find((r) => r.id === post.realm_id) : undefined;

    let where: string;
    let href: string;
    if (realm?.is_commons) {
      where = 'posted in The Commons';
      href = '/';
    } else if (realm) {
      where = `posted in ${realm.name}`;
      href = `/realms/${realm.id}`;
    } else {
      where = 'posted';
      href = '/';
    }
    return { post, author, where, href };
  });

  // Restrained empty state: nothing to show → collapse entirely.
  if (items.length === 0) return null;

  return (
    <section aria-label={HEADING}>
      <h3 className="text-[11px] font-mono uppercase tracking-[0.1em] text-ink-3 mb-4">{HEADING}</h3>
      <div className="space-y-1">
        {items.map(({ post, author, where, href }) => {
          const isCharacter = author.kind === 'character';
          const avatar = isCharacter && post.character_avatar_url ? post.character_avatar_url : null;
          return (
            <Link
              key={post.id}
              to={href}
              className="flex items-start gap-2.5 px-2 py-1.5 -mx-2 rounded-xl hover:bg-surface-elevated transition-colors"
            >
              {avatar ? (
                <img
                  src={avatar}
                  alt={author.label}
                  className="w-8 h-8 rounded-full object-cover border border-edge-md flex-shrink-0"
                  loading="lazy"
                  decoding="async"
                />
              ) : (
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold flex-shrink-0 ${
                    isCharacter ? 'bg-gem-soft text-gem' : 'bg-surface-elevated text-ink-3'
                  }`}
                >
                  {isCharacter ? author.label.charAt(0) : '✦'}
                </div>
              )}
              <div className="min-w-0 flex-1 leading-snug">
                <p className="text-[13px] text-ink-2">
                  <span className={isCharacter ? 'font-medium text-ink' : 'font-medium text-ink-2'}>
                    {author.label}
                  </span>{' '}
                  <span className="text-ink-3">{where}</span>
                </p>
                <span className="text-[11px] font-mono text-ink-3">{compactTimestamp(post.created_at)}</span>
              </div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
