import type { StorySpacePost } from '@/lib/types';

type SourceType = 'user' | 'ai_assisted' | 'ai_generated';

const SOURCE_PILLS: Record<SourceType, { label: string; className: string }> = {
  user:          { label: '✍️ User Written', className: 'text-ink-2/80  border-edge-md  bg-surface-elevated'  },
  ai_assisted:   { label: '✨ AI Assisted',  className: 'text-purple-400/80 border-purple-800/50 bg-purple-950/30' },
  ai_generated:  { label: '🤖 AI Generated', className: 'text-blue-400/70  border-blue-800/40  bg-blue-950/20'  },
};

function SourcePill({ sourceType }: { sourceType?: SourceType | null }) {
  const pill = SOURCE_PILLS[sourceType ?? 'user'];
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded border select-none ${pill.className}`}>
      {pill.label}
    </span>
  );
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  const now = Date.now();
  const diffMs = now - d.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function Avatar({ url, name }: { url?: string; name: string }) {
  const initial = name.charAt(0).toUpperCase();
  return (
    <div className="w-7 h-7 rounded-full flex-shrink-0 overflow-hidden bg-surface-elevated flex items-center justify-center border border-edge-md">
      {url ? (
        <img src={url} alt={name} className="w-full h-full object-cover" />
      ) : (
        <span className="text-[11px] font-semibold text-ink-2">{initial}</span>
      )}
    </div>
  );
}

function PostItem({ post }: { post: StorySpacePost }) {
  // Character-first: the character is the only public identity. A post with no
  // character renders as an unlinked "Wanderer" — never the account username.
  const isCharacter = Boolean(post.character_name);
  const displayName = post.character_name ?? 'Wanderer';
  const avatarName = displayName;

  return (
    <article className="group py-3 border-b border-edge last:border-0">
      {/* Byline */}
      <div className="flex items-center gap-2 mb-1.5">
        <Avatar url={post.character_avatar_url} name={avatarName} />
        <span
          className={`text-sm font-medium leading-none ${
            isCharacter ? 'text-gem' : 'text-ink-2'
          }`}
        >
          {displayName}
        </span>
        <SourcePill sourceType={post.source_type} />
        <span className="ml-auto text-[11px] text-ink-3 group-hover:text-ink-3 transition-colors leading-none flex-shrink-0">
          {formatTimestamp(post.created_at)}
        </span>
      </div>

      {/* Content */}
      <div className="pl-9">
        <p
          className={`text-sm leading-relaxed whitespace-pre-wrap ${
            post.content_type === 'ooc'
              ? 'text-ink-3 italic'
              : post.content_type === 'narration'
              ? 'text-ink-2 italic'
              : 'text-ink'
          }`}
        >
          {post.content_type === 'ooc' && (
            <span className="not-italic text-[10px] font-semibold uppercase tracking-wide text-ink-3 mr-1.5">
              OOC
            </span>
          )}
          {post.content}
        </p>
      </div>
    </article>
  );
}

interface Props {
  posts: StorySpacePost[];
  loading: boolean;
}

export default function PostList({ posts, loading }: Props) {
  if (loading) {
    return (
      <div className="space-y-3 px-4 py-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="animate-pulse">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-7 h-7 rounded-full bg-surface-elevated" />
              <div className="h-3 bg-surface-elevated rounded w-24" />
            </div>
            <div className="pl-9 space-y-1.5">
              <div className="h-3 bg-surface-elevated rounded w-full" />
              <div className="h-3 bg-surface-elevated rounded w-3/4" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (posts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[12rem] text-center px-6 py-10">
        <p className="text-ink-3 text-sm">Nothing here yet.</p>
        <p className="text-ink-3 text-xs mt-1">Be the first to write something.</p>
      </div>
    );
  }

  return (
    <div className="px-4 py-2">
      {posts.map((p) => (
        <PostItem key={p.id} post={p} />
      ))}
    </div>
  );
}
