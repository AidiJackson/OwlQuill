/**
 * StoryLabSession — loads a named Story record and renders StoryLabEngine
 * with the story's real ID (UUID from the DB, not a localStorage timestamp).
 *
 * Route: /storylab/:storyId
 */
import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { StoryRecord } from '@/lib/types';
import StoryLabEngine from '@/features/storylab/StoryLabEngine';
import { isUuidLike, deriveReadableTitle } from '@/lib/storyTitleUtils';

export default function StoryLabSession() {
  const { storyId } = useParams<{ storyId: string }>();
  const navigate = useNavigate();

  const [story, setStory]       = useState<StoryRecord | null>(null);
  const [loading, setLoading]   = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!storyId) {
      navigate('/storylab', { replace: true });
      return;
    }
    setLoading(true);
    setNotFound(false);
    apiClient.getStory(storyId)
      .then((s) => setStory(s))
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [storyId, navigate]);

  if (loading) {
    return (
      <div className="min-h-screen bg-app flex items-center justify-center">
        <div className="text-ink-3 text-sm animate-pulse">Loading story…</div>
      </div>
    );
  }

  if (notFound || !story) {
    return (
      <div className="min-h-screen bg-app flex flex-col items-center justify-center gap-4">
        <p className="text-ink-2 text-sm">Story not found or you don't have access.</p>
        <button
          type="button"
          onClick={() => navigate('/storylab')}
          className="px-4 py-2 text-sm rounded-xl border border-edge bg-surface hover:bg-surface-elevated text-ink-2 hover:text-ink transition"
        >
          ← Back to StoryLab
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-app text-ink flex flex-col">
      {/* Story header bar */}
      <div className="flex items-center gap-3 px-4 md:px-6 py-4 border-b border-edge bg-app backdrop-blur-sm">
        <button
          type="button"
          onClick={() => navigate('/storylab')}
          className="text-[12px] text-ink-3 hover:text-ink transition shrink-0"
        >
          {'\u2190'} StoryLab
        </button>
        <div
          className="w-5 h-5 rounded-md shrink-0"
          style={{ backgroundColor: story.cover_color }}
        />
        <h1 className="font-serif text-lg font-medium text-ink truncate flex-1">
          {story.title && !isUuidLike(story.title)
            ? story.title
            : deriveReadableTitle(story.premise)}
        </h1>
        {story.genre && (
          <span className="font-mono text-[11px] text-ink-3 shrink-0 capitalize tracking-wide">{story.genre}</span>
        )}
      </div>

      {/* Engine — full height below the header bar */}
      <div className="flex-1 flex flex-col min-h-0">
        <StoryLabEngine storyId={story.id} storyTitle={story.title} storyRecord={story} />
      </div>
    </div>
  );
}
