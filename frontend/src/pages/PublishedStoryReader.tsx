import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import { useAuthStore } from '@/lib/store';
import type { PublishedStory } from '@/lib/types';

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

export default function PublishedStoryReader() {
  const { storyId } = useParams<{ storyId: string }>();
  const currentUser = useAuthStore((state) => state.user);

  const [story, setStory] = useState<PublishedStory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!storyId) return;
    setLoading(true);
    setError('');
    apiClient
      .getPublishedStory(Number(storyId))
      .then(setStory)
      .catch((err: unknown) => {
        setError((err as Error).message || 'Could not load story.');
      })
      .finally(() => setLoading(false));
  }, [storyId]);

  // ── Loading ──────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="max-w-2xl mx-auto px-6 py-12 space-y-4">
        <div className="h-8 bg-gray-800 rounded animate-pulse w-2/3" />
        <div className="h-4 bg-gray-800 rounded animate-pulse w-full" />
        <div className="h-4 bg-gray-800 rounded animate-pulse w-4/5" />
        <div className="space-y-3 mt-8">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-4 bg-gray-800 rounded animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (error || !story) {
    return (
      <div className="max-w-2xl mx-auto px-6 py-10">
        <Link to="/" className="text-sm text-gray-500 hover:text-gray-300 transition-colors mb-6 inline-block">
          ← Home
        </Link>
        <div className="rounded-xl bg-red-900/20 border border-red-700/40 px-4 py-3 text-sm text-red-400">
          {error || 'Story not found.'}
        </div>
      </div>
    );
  }

  const publisherLabel =
    currentUser?.id === story.publisher_user_id
      ? `@${currentUser.username}`
      : null;

  const publishedDate = story.published_at ?? story.created_at;

  // ── Story layout ─────────────────────────────────────────────────────────────

  return (
    <div className="max-w-2xl mx-auto px-4 py-10">
      {/* Header */}
      <header className="mb-8 border-b border-gray-800/60 pb-6">
        <h1 className="text-2xl font-semibold text-gray-100 leading-tight mb-3">
          {story.title}
        </h1>

        {story.summary && (
          <p className="text-base text-gray-400 leading-relaxed mb-4">
            {story.summary}
          </p>
        )}

        <div className="flex items-center gap-3 text-xs text-gray-600 flex-wrap">
          {publisherLabel && (
            <span className="text-gray-500">{publisherLabel}</span>
          )}
          <span>{formatDate(publishedDate)}</span>
          <span>·</span>
          <span>{story.segment_count} {story.segment_count === 1 ? 'segment' : 'segments'}</span>
        </div>
      </header>

      {/* Segments */}
      <div className="space-y-6">
        {story.segments.map((seg) => (
          <section key={seg.id}>
            {seg.character_name_snap && (
              <p className="text-xs font-semibold uppercase tracking-wide text-emerald-500 mb-1.5">
                {seg.character_name_snap}
              </p>
            )}
            <p
              className={`text-base leading-loose whitespace-pre-wrap ${
                seg.content_type === 'narration'
                  ? 'text-gray-300 italic'
                  : seg.content_type === 'ooc'
                  ? 'text-gray-500 italic text-sm'
                  : 'text-gray-200'
              }`}
            >
              {seg.content}
            </p>
          </section>
        ))}
      </div>

      {/* Footer */}
      <footer className="mt-12 pt-6 border-t border-gray-800/60 text-center">
        <p className="text-xs text-gray-700">Published on Ficshon</p>
      </footer>
    </div>
  );
}
