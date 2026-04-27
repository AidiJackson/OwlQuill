import { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { StorySpaceRead, StorySpacePost } from '@/lib/types';

export default function StorySpacePublish() {
  const { spaceId } = useParams<{ spaceId: string }>();
  const navigate = useNavigate();

  const [space, setSpace] = useState<StorySpaceRead | null>(null);
  const [posts, setPosts] = useState<StorySpacePost[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');

  useEffect(() => {
    if (!spaceId) return;
    const sid = Number(spaceId);
    setLoading(true);
    setLoadError('');
    apiClient
      .getStorySpace(sid)
      .then(async (data) => {
        setSpace(data);
        const storyChannel = data.channels.find((ch) => ch.channel_type === 'story');
        if (!storyChannel) {
          setPosts([]);
          return;
        }
        const channelPosts = await apiClient.getSpacePosts(sid, storyChannel.id);
        setPosts(channelPosts);
      })
      .catch((err: unknown) => {
        setLoadError((err as Error).message || 'Could not load space.');
      })
      .finally(() => setLoading(false));
  }, [spaceId]);

  function togglePost(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!spaceId || !title.trim() || selected.size === 0) return;
    setSubmitting(true);
    setSubmitError('');
    try {
      // Preserve visible post order
      const orderedIds = posts.filter((p) => selected.has(p.id)).map((p) => p.id);
      const story = await apiClient.publishStory(Number(spaceId), {
        title: title.trim(),
        summary: summary.trim() || undefined,
        post_ids: orderedIds,
      });
      navigate(`/stories/${story.id}`);
    } catch (err: unknown) {
      setSubmitError((err as Error).message || 'Publish failed. Please try again.');
      setSubmitting(false);
    }
  }

  // ── Loading ──────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="space-y-3 w-64">
          <div className="h-5 bg-gray-800 rounded animate-pulse w-48" />
          <div className="h-3 bg-gray-800 rounded animate-pulse w-64" />
        </div>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="max-w-xl mx-auto px-6 py-10">
        <Link to={`/spaces/${spaceId}`} className="text-sm text-gray-500 hover:text-gray-300 transition-colors mb-6 inline-block">
          ← Back to Space
        </Link>
        <div className="rounded-xl bg-red-900/20 border border-red-700/40 px-4 py-3 text-sm text-red-400">
          {loadError}
        </div>
      </div>
    );
  }

  const hasStoryChannel = space?.channels.some((ch) => ch.channel_type === 'story');

  // ── Full layout ──────────────────────────────────────────────────────────────

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      {/* Back link */}
      <Link
        to={`/spaces/${spaceId}`}
        className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-300 transition-colors mb-6"
      >
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
        {space?.name ?? 'Back'}
      </Link>

      {/* Header */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-100">Publish Story</h1>
        <p className="text-sm text-gray-500 mt-1">
          Only Story channel posts can be published.{' '}
          <span className="text-gray-600">Chat and Planning stay private.</span>
        </p>
      </div>

      {/* No story channel */}
      {!hasStoryChannel && (
        <div className="rounded-xl bg-gray-800/50 border border-gray-700/40 px-5 py-8 text-center">
          <p className="text-gray-400 text-sm">This space has no Story channel.</p>
          <p className="text-gray-600 text-xs mt-1">Add a story channel before publishing.</p>
        </div>
      )}

      {/* Empty story channel */}
      {hasStoryChannel && posts.length === 0 && (
        <div className="rounded-xl bg-gray-800/50 border border-gray-700/40 px-5 py-8 text-center">
          <p className="text-gray-400 text-sm">No story posts yet.</p>
          <p className="text-gray-600 text-xs mt-1">Write something in the Story channel first.</p>
        </div>
      )}

      {/* Publish form */}
      {hasStoryChannel && posts.length > 0 && (
        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-6">
          {/* Title */}
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1.5">
              Title <span className="text-emerald-500">*</span>
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Give your story a title"
              maxLength={200}
              required
              className="w-full bg-gray-900 border border-gray-700/60 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-emerald-600/60 focus:ring-1 focus:ring-emerald-600/30 transition-colors"
            />
          </div>

          {/* Summary */}
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1.5">
              Summary <span className="text-gray-700">(optional)</span>
            </label>
            <textarea
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="A short description readers will see"
              rows={3}
              className="w-full bg-gray-900 border border-gray-700/60 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-emerald-600/60 focus:ring-1 focus:ring-emerald-600/30 transition-colors resize-none"
            />
          </div>

          {/* Post selector */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Select posts
              </label>
              <span className="text-xs text-gray-600">
                {selected.size} of {posts.length} selected
              </span>
            </div>

            <div className="rounded-xl border border-gray-800/80 overflow-hidden divide-y divide-gray-800/60">
              {posts.map((post) => {
                const isSelected = selected.has(post.id);
                const displayName = post.character_name ?? `@${post.author_username}`;
                return (
                  <label
                    key={post.id}
                    className={`flex items-start gap-3 px-4 py-3 cursor-pointer transition-colors ${
                      isSelected ? 'bg-emerald-950/30' : 'hover:bg-gray-900/60'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => togglePost(post.id)}
                      className="mt-0.5 flex-shrink-0 accent-emerald-500"
                    />
                    <div className="flex-1 min-w-0">
                      <span
                        className={`text-xs font-medium ${
                          post.character_name ? 'text-emerald-400' : 'text-gray-500'
                        }`}
                      >
                        {displayName}
                      </span>
                      <p className="text-sm text-gray-300 mt-0.5 leading-relaxed line-clamp-3 whitespace-pre-wrap">
                        {post.content}
                      </p>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>

          {/* Error */}
          {submitError && (
            <div className="rounded-lg bg-red-900/20 border border-red-700/40 px-4 py-2.5 text-sm text-red-400">
              {submitError}
            </div>
          )}

          {/* Submit */}
          <div className="flex items-center gap-3 pt-1">
            <button
              type="submit"
              disabled={submitting || !title.trim() || selected.size === 0}
              className="px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium transition-colors"
            >
              {submitting ? 'Publishing…' : 'Publish Story'}
            </button>
            <Link
              to={`/spaces/${spaceId}`}
              className="px-4 py-2 rounded-lg text-sm text-gray-500 hover:text-gray-300 transition-colors"
            >
              Cancel
            </Link>
          </div>
        </form>
      )}
    </div>
  );
}
