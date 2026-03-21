import { useState, useEffect } from 'react';
import { apiClient } from '@/lib/apiClient';
import type { Comment } from '@/lib/types';

interface CommentSectionProps {
  postId: number;
  defaultExpanded?: boolean;
}

export default function CommentSection({ postId, defaultExpanded = false }: CommentSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [comments, setComments] = useState<Comment[]>([]);
  const [loading, setLoading] = useState(false);
  const [content, setContent] = useState('');
  const [contentType, setContentType] = useState<'ic' | 'ooc' | 'narration'>('ooc');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (expanded) {
      setLoading(true);
      apiClient
        .getPostComments(postId)
        .then(setComments)
        .catch((err) => console.error('Failed to load comments:', err))
        .finally(() => setLoading(false));
    }
  }, [expanded, postId]);

  const handleSubmit = async () => {
    if (!content.trim() || submitting) return;

    setSubmitting(true);
    try {
      await apiClient.createComment(postId, {
        content: content.trim(),
        content_type: contentType,
      });
      setContent('');
      const updated = await apiClient.getPostComments(postId);
      setComments(updated);
    } catch (error) {
      console.error('Failed to create comment:', error);
    } finally {
      setSubmitting(false);
    }
  };

  const getTypeBadge = (type?: string) => {
    if (!type) return null;
    const badges: Record<string, { label: string; className: string }> = {
      ic: { label: 'IC', className: 'bg-emerald-600 text-white' },
      ooc: { label: 'OOC', className: 'bg-blue-600 text-white' },
      narration: { label: 'NARRATION', className: 'bg-amber-600 text-white' },
    };
    const badge = badges[type];
    if (!badge) return null;
    return (
      <span className={`px-1.5 py-0.5 text-xs font-semibold rounded ${badge.className}`}>
        {badge.label}
      </span>
    );
  };

  return (
    <div className="mt-4 pt-3 border-t border-gray-800">
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-sm text-gray-400 hover:text-gray-200 transition-colors"
      >
        {expanded ? 'Hide comments' : `Comments${comments.length > 0 ? ` (${comments.length})` : ''}`}
      </button>

      {expanded && (
        <div className="mt-3">
          {loading ? (
            <p className="text-sm text-gray-500">Loading comments...</p>
          ) : comments.length > 0 ? (
            <div className="space-y-3 mb-4">
              {comments.map((comment) => (
                <div key={comment.id} className="pl-3 border-l-2 border-gray-700">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    {/* Character-first identity, username fallback */}
                    {comment.character_name ? (
                      <div className="flex items-center gap-1 flex-shrink-0">
                        {comment.character_avatar_url ? (
                          <img
                            src={comment.character_avatar_url}
                            alt={comment.character_name}
                            className="w-5 h-5 rounded object-cover border border-gray-700"
                          />
                        ) : (
                          <div className="w-5 h-5 rounded bg-emerald-600/20 border border-emerald-500/20 flex items-center justify-center text-[9px] font-semibold text-emerald-400 flex-shrink-0">
                            {comment.character_name.charAt(0)}
                          </div>
                        )}
                        <span className="text-sm font-medium text-emerald-400">
                          {comment.character_name}
                        </span>
                      </div>
                    ) : comment.author_username ? (
                      <span className="text-sm text-gray-400 flex-shrink-0">
                        @{comment.author_username}
                      </span>
                    ) : null}
                    {getTypeBadge(comment.content_type)}
                    <span className="text-xs text-gray-500">
                      {new Date(comment.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  <p className="text-sm text-gray-300 whitespace-pre-wrap">{comment.content}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500 mb-4">No comments yet.</p>
          )}

          {/* Comment composer */}
          <div className="space-y-2">
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Write a comment..."
              className="textarea text-sm"
              rows={2}
            />
            <div className="flex items-center gap-2">
              <select
                value={contentType}
                onChange={(e) =>
                  setContentType(e.target.value as 'ic' | 'ooc' | 'narration')
                }
                className="input text-sm py-1 w-auto"
              >
                <option value="ic">IC</option>
                <option value="ooc">OOC</option>
                <option value="narration">Narration</option>
              </select>
              <button
                onClick={handleSubmit}
                disabled={!content.trim() || submitting}
                className="btn btn-primary text-sm py-1 px-3"
              >
                {submitting ? 'Posting...' : 'Comment'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
