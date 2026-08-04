import { useState, useEffect } from 'react';
import { apiClient } from '@/lib/apiClient';
import { useAuthStore } from '@/lib/store';
import { authorLink } from '@/lib/authorLink';
import type { Comment, Character } from '@/lib/types';

interface CommentSectionProps {
  postId: number;
  characters?: Character[];
  defaultExpanded?: boolean;
  /** Server-sent count from the parent post, used for the collapsed label so
   *  an existing comment is announced before the comments are fetched. */
  commentCount?: number;
}

export default function CommentSection({
  postId,
  characters = [],
  defaultExpanded = false,
  commentCount,
}: CommentSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [comments, setComments] = useState<Comment[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [content, setContent] = useState('');
  const [contentType, setContentType] = useState<'ic' | 'ooc' | 'narration'>('ooc');
  const [composerCharId, setComposerCharId] = useState<number | null>(null);
  const [commentError, setCommentError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const activeCharacterId = useAuthStore((s) => s.user?.active_character?.id);
  const wandererName = useAuthStore((s) => s.user?.username);

  // Default the replying identity to the ACTIVE character; single-character
  // accounts resolve automatically. Multi-character with no selection picks explicitly.
  useEffect(() => {
    if (composerCharId !== null) return;
    if (activeCharacterId && characters.some((c) => c.id === activeCharacterId)) {
      setComposerCharId(activeCharacterId);
    } else if (characters.length === 1) {
      setComposerCharId(characters[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [characters, activeCharacterId]);

  useEffect(() => {
    if (expanded) {
      setLoading(true);
      apiClient
        .getPostComments(postId)
        .then((loadedComments) => {
          setComments(loadedComments);
          setLoaded(true);
        })
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

  // Before the comments are fetched the only truthful count is the server's;
  // once they are, the fetched list is authoritative (it reflects blocking and
  // the viewer's own new comment).
  const shownCount = loaded ? comments.length : commentCount ?? 0;

  const getTypeBadge = (type?: string) => {
    if (!type) return null;
    const badges: Record<string, { label: string; className: string }> = {
      ic: { label: 'IC', className: 'bg-gem-soft text-gem border border-gem/25' },
      ooc: { label: 'OOC', className: 'bg-surface-elevated text-ink-3 border border-edge' },
      narration: { label: 'NARRATION', className: 'bg-amber-950/20 text-amber-400/80 border border-amber-800/40' },
    };
    const badge = badges[type];
    if (!badge) return null;
    return (
      <span className={`px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-[0.06em] rounded ${badge.className}`}>
        {badge.label}
      </span>
    );
  };

  return (
    <div className="mt-3 pt-3 border-t border-edge">
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-sm text-ink-2 hover:text-ink transition-colors"
      >
        {expanded ? 'Hide comments' : `Comments${shownCount > 0 ? ` (${shownCount})` : ''}`}
      </button>

      {expanded && (
        <div className="mt-3">
          {loading ? (
            <p className="text-sm text-ink-3">Loading comments...</p>
          ) : comments.length > 0 ? (
            <div className="space-y-3 mb-4">
              {comments.map((comment) => (
                <div key={comment.id} className="pl-3 border-l-2 border-edge-md">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    {/* One public identity per account type: a Writer's comment
                        is the character; a Wanderer's is their Wanderer
                        username and account sigil. Never a bare "Wanderer"
                        placeholder when the server sent us a real name. */}
                    {(() => {
                      const author = authorLink(comment);
                      const isCharacter = author.kind === 'character';
                      return (
                        <div className="flex items-center gap-1 flex-shrink-0">
                          {author.avatarUrl ? (
                            <img
                              src={author.avatarUrl}
                              alt={author.label}
                              className="w-5 h-5 rounded-full object-cover border border-edge-md"
                            />
                          ) : (
                            <div
                              className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-semibold flex-shrink-0 ${
                                isCharacter
                                  ? 'bg-gem-soft text-gem'
                                  : 'bg-surface-elevated border border-edge text-ink-3'
                              }`}
                            >
                              {author.label.charAt(0).toUpperCase()}
                            </div>
                          )}
                          {/* The author outranks the timestamp: full-strength
                              ink and a heavier weight against the muted,
                              secondary date beside it. */}
                          <span
                            className={`text-sm font-semibold ${
                              isCharacter ? 'text-gem' : 'text-ink'
                            }`}
                          >
                            {author.label}
                          </span>
                        </div>
                      );
                    })()}
                    {getTypeBadge(comment.content_type)}
                    <span className="text-xs font-mono text-ink-3">
                      {new Date(comment.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  <p className="text-sm text-ink-2 whitespace-pre-wrap">{comment.content}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-ink-3 mb-4">No comments yet.</p>
          )}

          {/* Comment composer */}
          <div className="space-y-2">
            {/* Wanderer replying identity — their public Wanderer username,
                stated plainly so they know what others will see. */}
            {characters.length === 0 && wandererName && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-ink-3 flex-shrink-0">Replying as</span>
                <span className="text-xs text-ink-2 font-medium">{wandererName}</span>
              </div>
            )}
            {/* Replying identity */}
            {characters.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-ink-3 flex-shrink-0">Replying as</span>
                {characters.length === 1 ? (
                  <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-surface-elevated border border-edge text-xs select-none">
                    {characters[0].avatar_url ? (
                      <img
                        src={characters[0].avatar_url}
                        alt={characters[0].name}
                        className="w-4 h-4 rounded-full object-cover flex-shrink-0"
                      />
                    ) : (
                      <div className="w-4 h-4 rounded-full bg-gem-soft flex items-center justify-center text-[8px] font-semibold text-gem flex-shrink-0">
                        {characters[0].name.charAt(0)}
                      </div>
                    )}
                    <span className="text-gem font-medium">{characters[0].name}</span>
                  </div>
                ) : (
                  <select
                    value={composerCharId ?? ''}
                    onChange={(e) => setComposerCharId(e.target.value ? Number(e.target.value) : null)}
                    className="bg-surface-elevated border border-edge rounded-lg px-2 py-1 text-xs text-ink-2 cursor-pointer focus:outline-none w-auto"
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
              className="w-full px-3 py-2 bg-surface-elevated border border-edge rounded-lg text-sm text-ink placeholder:text-ink-3 focus:outline-none min-h-[60px]"
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
                className="bg-surface-elevated border border-edge rounded-lg px-2.5 py-1 text-sm text-ink-2 cursor-pointer focus:outline-none w-auto"
              >
                <option value="ic">IC</option>
                <option value="ooc">OOC</option>
                <option value="narration">Narration</option>
              </select>
              <button
                onClick={handleSubmit}
                disabled={!content.trim() || submitting}
                className="px-3 py-1 rounded-lg text-sm font-semibold bg-gem text-gem-ink hover:bg-gem/90 transition-colors disabled:opacity-40"
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
