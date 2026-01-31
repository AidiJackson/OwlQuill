import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { Scene, ScenePost, Character } from '@/lib/types';

export default function SceneDetail() {
  const { sceneId } = useParams<{ sceneId: string }>();
  const navigate = useNavigate();
  const bottomRef = useRef<HTMLDivElement>(null);

  const [scene, setScene] = useState<Scene | null>(null);
  const [posts, setPosts] = useState<ScenePost[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);

  // Composer state
  const [content, setContent] = useState('');
  const [characterId, setCharacterId] = useState<number | undefined>(undefined);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadData = async () => {
      if (!sceneId) return;
      try {
        const [sceneData, postsData, charsData] = await Promise.all([
          apiClient.getScene(Number(sceneId)),
          apiClient.listScenePosts(Number(sceneId)),
          apiClient.getCharacters(),
        ]);
        setScene(sceneData);
        setPosts(postsData);
        setCharacters(charsData);
      } catch (err) {
        console.error('Failed to load scene:', err);
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, [sceneId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [posts.length]);

  const handleSubmit = async () => {
    if (!sceneId || !content.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const newPost = await apiClient.createScenePost(Number(sceneId), {
        content: content.trim(),
        character_id: characterId,
      });
      setPosts((prev) => [...prev, newPost]);
      setContent('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to post');
    } finally {
      setSubmitting(false);
    }
  };

  const visibilityBadge = (v: string) => {
    const map: Record<string, { label: string; className: string }> = {
      PUBLIC: { label: 'Public', className: 'bg-green-600 text-white' },
      UNLISTED: { label: 'Unlisted', className: 'bg-yellow-600 text-white' },
      PRIVATE: { label: 'Private', className: 'bg-red-600 text-white' },
    };
    const b = map[v] || map.PUBLIC;
    return <span className={`px-2 py-0.5 text-xs font-semibold rounded ${b.className}`}>{b.label}</span>;
  };

  if (loading) {
    return (
      <div className="p-8">
        <p className="text-gray-400">Loading scene...</p>
      </div>
    );
  }

  if (!scene) {
    return (
      <div className="p-8">
        <p className="text-gray-400">Scene not found</p>
        <button onClick={() => navigate(-1)} className="btn btn-secondary mt-4">
          Go Back
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-8">
      {/* Scene header */}
      <div className="card mb-6">
        <div className="flex items-center justify-between mb-2">
          <h1 className="text-2xl font-bold">{scene.title}</h1>
          {visibilityBadge(scene.visibility)}
        </div>
        {scene.description && (
          <p className="text-gray-300 text-sm whitespace-pre-wrap">{scene.description}</p>
        )}
        <p className="text-xs text-gray-500 mt-2">
          Created {new Date(scene.created_at).toLocaleDateString()}
        </p>
      </div>

      {/* Scene posts / turns */}
      <div className="space-y-3 mb-6">
        {posts.length === 0 ? (
          <div className="card text-center">
            <p className="text-gray-400">No turns yet. Write the opening below.</p>
          </div>
        ) : (
          posts.map((p) => (
            <div key={p.id} className="card">
              <div className="flex items-center gap-2 mb-2">
                {p.character_name ? (
                  <span className="text-sm font-medium text-owl-400">{p.character_name}</span>
                ) : p.author_username ? (
                  <span className="text-sm text-gray-400">@{p.author_username}</span>
                ) : null}
                <span className="text-xs text-gray-500">
                  {new Date(p.created_at).toLocaleString()}
                </span>
              </div>
              <p className="text-gray-300 whitespace-pre-wrap">{p.content}</p>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* Composer */}
      <div className="card">
        <h3 className="text-lg font-semibold mb-3">Add a Turn</h3>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          className="textarea w-full mb-3"
          placeholder="Write your turn..."
          rows={4}
        />
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={characterId ?? ''}
            onChange={(e) => setCharacterId(e.target.value ? Number(e.target.value) : undefined)}
            className="input w-auto text-sm"
          >
            <option value="">Post as yourself</option>
            {characters.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <button
            onClick={handleSubmit}
            disabled={submitting || !content.trim()}
            className="btn btn-primary text-sm ml-auto"
          >
            {submitting ? 'Posting...' : 'Post Turn'}
          </button>
        </div>
        {error && <p className="text-red-400 text-sm mt-2">{error}</p>}
      </div>
    </div>
  );
}
