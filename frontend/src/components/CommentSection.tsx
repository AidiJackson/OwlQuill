import { useState, useEffect, useRef } from 'react';
import { Trash2 } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import { useAuthStore } from '@/lib/store';
import { authorLink } from '@/lib/authorLink';
import type { Comment, Character } from '@/lib/types';
import { CompositionTracker } from '@/lib/composition';
import { PostTypeBadge } from '@/components/PostBadges';
import ConfirmDialog from '@/components/ConfirmDialog';

interface CommentSectionProps {
  postId: number;
  characters?: Character[];
  defaultExpanded?: boolean;
  /** Server-sent count from the parent post, used for the collapsed label so
   *  an existing comment is announced before the comments are fetched. */
  commentCount?: number;
  /** Told +1 / -1 when the viewer adds or deletes a comment here, so a parent
   *  holding the post's `comment_count` can keep it true (e.g. for PostMenu's
   *  delete copy). A delta, not a length: the fetched list omits blocked
   *  users' comments, which still exist and still count. */
  onCommentCountChange?: (delta: number) => void;
}

export default function CommentSection({
  postId,
  characters = [],
  defaultExpanded = false,
  commentCount,
  onCommentCountChange,
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
  const composition = useRef(
    new CompositionTracker('comment', { targetKind: 'comment', targetRef: String(postId) }),
  ).current;

  const activeCharacterId = useAuthStore((s) => s.user?.active_character?.id);
  const wandererName = useAuthStore((s) => s.user?.username);
  const viewerId = useAuthStore((s) => s.user?.id);

  // Author-only delete. `author_user_id` reaches the client for the author's
  // own comments (and for Wanderer comments); the server re-checks it anyway.
  const [pendingDelete, setPendingDelete] = useState<Comment | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

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
      const sessionId = await composition.commit();
      await apiClient.createComment(postId, {
        content: content.trim(),
        content_type: contentType,
        ...(composerCharId ? { character_id: composerCharId } : {}),
        ...(sessionId ? { composition_session_id: sessionId } : {}),
      });
      composition.reset();
      setContent('');
      onCommentCountChange?.(1);
      const updated = await apiClient.getPostComments(postId);
      setComments(updated);
    } catch (error) {
      console.error('Failed to create comment:', error);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!pendingDelete || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await apiClient.deleteComment(pendingDelete.id);
      const goneId = pendingDelete.id;
      setComments((prev) => prev.filter((c) => c.id !== goneId));
      onCommentCountChange?.(-1);
      setPendingDelete(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'Failed to delete comment');
    } finally {
      setDeleting(false);
    }
  };

  // Before the comments are fetched the only truthful count is the server's;
  // once they are, the fetched list is authoritative (it reflects blocking and
  // the viewer's own new comment).
  const shownCount = loaded ? comments.length : commentCount ?? 0;

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
                    <PostTypeBadge contentType={comment.content_type} />
                    <span className="text-xs font-mono text-ink-3">
                      {new Date(comment.created_at).toLocaleDateString()}
                    </span>
                    {viewerId !== undefined && comment.author_user_id === viewerId && (
                      <button
                        type="button"
                        onClick={() => { setDeleteError(null); setPendingDelete(comment); }}
                        className="ml-auto p-1 rounded text-ink-3 hover:text-red-400 hover:bg-surface-elevated transition-colors"
                        aria-label="Delete comment"
                        title="Delete comment"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                  <p className="fic-read-sm fic-ooc whitespace-pre-wrap">{comment.content}</p>
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
              ref={composition.attach}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Write a comment..."
              className="fic-read-sm w-full px-3 py-2 bg-surface-elevated border border-edge rounded-lg text-ink placeholder:text-ink-3 focus:outline-none min-h-[60px]"
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

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete comment?"
        confirmLabel="Delete"
        danger
        busy={deleting}
        error={deleteError}
        onConfirm={handleDelete}
        onCancel={() => { setPendingDelete(null); setDeleteError(null); }}
      >
        <p>This permanently removes your comment. This can't be undone.</p>
      </ConfirmDialog>
    </div>
  );
}
