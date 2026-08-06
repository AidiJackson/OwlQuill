import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
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
      <div className="max-w-[680px] mx-auto px-6 py-14 space-y-4">
        <div className="h-9 bg-surface-elevated rounded animate-pulse w-2/3" />
        <div className="h-4 bg-surface-elevated rounded animate-pulse w-full" />
        <div className="h-4 bg-surface-elevated rounded animate-pulse w-4/5" />
        <div className="space-y-3 mt-8">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-4 bg-surface-elevated rounded animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (error || !story) {
    return (
      <div className="max-w-[680px] mx-auto px-6 py-10">
        <Link to="/" className="text-sm text-ink-3 hover:text-ink-2 transition-colors mb-6 inline-block">
          ← The Commons
        </Link>
        <div className="rounded-xl bg-red-900/20 border border-red-700/40 px-4 py-3 text-sm text-red-400">
          {error || 'Story not found.'}
        </div>
      </div>
    );
  }

  // Published stories are a public surface. Segments are attributed to their
  // character snapshots; the human account username is never shown as a byline —
  // not even to the publisher viewing their own story.
  const publishedDate = story.published_at ?? story.created_at;

  // ── Story layout ─────────────────────────────────────────────────────────────

  return (
    <div className="max-w-[680px] mx-auto px-5 sm:px-6 py-14">
      {/* Header — the title card */}
      <header className="mb-12 text-center">
        <h1 className="font-serif text-4xl sm:text-[44px] font-medium leading-[1.15] tracking-[-0.02em] text-ink mb-5">
          {story.title}
        </h1>

        {story.summary && (
          <p className="font-serif italic text-lg text-ink-2 leading-relaxed mb-6 max-w-[540px] mx-auto">
            {story.summary}
          </p>
        )}

        <div className="flex items-center justify-center gap-3 font-mono text-[11px] uppercase tracking-[0.1em] text-ink-3 flex-wrap">
          <span>{formatDate(publishedDate)}</span>
          <span aria-hidden="true">·</span>
          <span>{story.segment_count} {story.segment_count === 1 ? 'segment' : 'segments'}</span>
        </div>
        <div className="mt-8 mx-auto w-10 border-t border-edge-md" aria-hidden="true" />
      </header>

      {/* Segments — the manuscript */}
      <div className="space-y-8">
        {story.segments.map((seg) => (
          <section key={seg.id}>
            {seg.character_name_snap && (
              <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-gem mb-2">
                {seg.character_name_snap}
              </p>
            )}
            <p
              className={`whitespace-pre-wrap ${
                seg.content_type === 'narration'
                  ? 'fic-read fic-narration'
                  : seg.content_type === 'ooc'
                  ? 'fic-read-sm italic text-ink-3'
                  : 'fic-read'
              }`}
            >
              {seg.content}
            </p>
          </section>
        ))}
      </div>

      {/* Footer */}
      <footer className="mt-16 pt-8 text-center">
        <div className="mx-auto w-10 border-t border-edge-md mb-6" aria-hidden="true" />
        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-3">Published on Ficshon</p>
      </footer>
    </div>
  );
}
