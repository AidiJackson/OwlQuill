import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { StorySpaceRead } from '@/lib/types';

export default function StorySpaceDetail() {
  const { spaceId } = useParams<{ spaceId: string }>();
  const [space, setSpace] = useState<StorySpaceRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!spaceId) return;
    void (async () => {
      try {
        const data = await apiClient.getStorySpace(Number(spaceId));
        setSpace(data);
      } catch (err) {
        setError((err as Error).message || 'Could not load space.');
      } finally {
        setLoading(false);
      }
    })();
  }, [spaceId]);

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-10">
        <div className="h-6 bg-gray-800 rounded w-56 animate-pulse mb-4" />
        <div className="h-4 bg-gray-800 rounded w-80 animate-pulse" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-10">
        <Link to="/spaces" className="text-sm text-gray-500 hover:text-gray-300 transition-colors mb-6 inline-block">
          ← Back to Story Spaces
        </Link>
        <div className="rounded-xl bg-red-900/20 border border-red-700/40 px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-10">
      <Link to="/spaces" className="text-sm text-gray-500 hover:text-gray-300 transition-colors mb-6 inline-block">
        ← Back to Story Spaces
      </Link>

      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-100">{space?.name ?? '—'}</h1>
        {space?.description && (
          <p className="text-sm text-gray-500 mt-1">{space.description}</p>
        )}
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl px-6 py-10 text-center">
        <p className="text-gray-500 text-sm">Story Space loading soon</p>
        <p className="text-gray-700 text-xs mt-2">Channels and posts will appear here in the next release.</p>
      </div>
    </div>
  );
}
