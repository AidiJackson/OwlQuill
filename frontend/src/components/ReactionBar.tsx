import { useState, useEffect } from 'react';
import { apiClient } from '@/lib/apiClient';
import { useAuthStore } from '@/lib/store';
import type { Reaction } from '@/lib/types';

const REACTION_TYPES = [
  { type: 'heart', emoji: '\u2764\uFE0F' },
  { type: 'star', emoji: '\u2B50' },
  { type: 'eyes', emoji: '\uD83D\uDC40' },
];

interface ReactionBarProps {
  postId: number;
}

export default function ReactionBar({ postId }: ReactionBarProps) {
  const user = useAuthStore((s) => s.user);
  const [reactions, setReactions] = useState<Reaction[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiClient
      .getPostReactions(postId)
      .then(setReactions)
      .catch(() => {});
  }, [postId]);

  const getCount = (type: string) =>
    reactions.filter((r) => r.type === type).length;

  const getUserReaction = (type: string) =>
    reactions.find((r) => r.type === type && r.user_id === user?.id);

  const handleToggle = async (type: string) => {
    if (!user || busy) return;
    setBusy(true);
    try {
      const existing = getUserReaction(type);
      if (existing) {
        await apiClient.deleteReaction(existing.id);
        setReactions((prev) => prev.filter((r) => r.id !== existing.id));
      } else {
        const created = await apiClient.addReaction(postId, type);
        setReactions((prev) => [...prev, created]);
      }
    } catch (error) {
      console.error('Failed to toggle reaction:', error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-2 mt-3">
      {REACTION_TYPES.map(({ type, emoji }) => {
        const count = getCount(type);
        const isActive = !!getUserReaction(type);
        return (
          <button
            key={type}
            onClick={() => handleToggle(type)}
            disabled={busy}
            className={`flex items-center gap-1 px-2 py-1 rounded text-sm transition-colors ${
              isActive
                ? 'bg-gray-700 text-white'
                : 'text-gray-500 hover:bg-gray-800 hover:text-gray-300'
            }`}
          >
            <span>{emoji}</span>
            {count > 0 && <span className="text-xs">{count}</span>}
          </button>
        );
      })}
    </div>
  );
}
