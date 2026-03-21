import { useState, useEffect } from 'react';
import { apiClient } from '@/lib/apiClient';
import type { Comment, Character } from '@/lib/types';

interface CommentSectionProps {
  postId: number;
  characters?: Character[];
  defaultExpanded?: boolean;
}

export default function CommentSection({ postId, characters = [], defaultExpanded = false }: CommentSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [comments, setComments] = useState<Comment[]>([]);
  const [loading, setLoading] = useState(false);
  const [content, setContent] = useState('');
  const [contentType, setContentType] = useState<'ic' | 'ooc' | 'narration'>('ooc');
  const [composerCharId, setComposerCharId] = useState<number | null>(null);
  const [commentError, setCommentError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Auto-select when exactly one character exists; leave null for multi-char (requires explicit pick).
  useEffect(() => {
    if (characters.length === 1) setComposerCharId(characters[0].id);
  }, [characters]);

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
    // Require an explicit character selection when the user has characters
    if (characters.length > 0 && !composerCharId) {
      setCommentError('Select a character to reply as.');
      return;
    }
    setCommentError(null);
    setSubmitting(true);
    try {
      await apiClient.createComment(postId, {
        content: content.trim(),
        content_type: contentType,
        ...(composerCharId ? { character_id: composerCharId } : {}),
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
            {/* Replying identity */}
            {characters.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500 flex-shrink-0">Replying as</span>
                {characters.length === 1 ? (
                  <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-gray-800/60 border border-gray-700 text-xs select-none">
                    {characters[0].avatar_url ? (
                      <img
                        src={characters[0].avatar_url}
                        alt={characters[0].name}
                        className="w-4 h-4 rounded object-cover flex-shrink-0"
                      />
                    ) : (
                      <div className="w-4 h-4 rounded bg-emerald-600/20 border border-emerald-500/20 flex items-center justify-center text-[8px] font-semibold text-emerald-400 flex-shrink-0">
                        {characters[0].name.charAt(0)}
                      </div>
                    )}
                    <span className="text-emerald-400 font-medium">{characters[0].name}</span>
                  </div>
                ) : (
                  <select
                    value={composerCharId ?? ''}
                    onChange={(e) => setComposerCharId(e.target.value ? Number(e.target.value) : null)}
                    className="input text-xs py-1 w-auto"
                  >
                    <option value="" disabled>— select character —</option>
                    {characters.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                )}
              </div>
            )}
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Write a comment..."
              className="textarea text-sm"
              rows={2}
            />
            {commentError && (
              <p className="text-red-400 text-xs">{commentError}</p>
            )}
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
