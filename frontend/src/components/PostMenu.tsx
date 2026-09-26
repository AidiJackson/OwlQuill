import { useState, useRef, useEffect } from 'react';
import { MoreVertical } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import ConfirmDialog from '@/components/ConfirmDialog';

interface PostMenuProps {
  postId: number;
  onDeleted: (postId: number) => void;
  /** The post's server-sent `comment_count`, when the caller already has it.
   *  Only used to state the consequence exactly; omitted, the copy is generic. */
  commentCount?: number;
}

/** What deleting a post takes with it. DELETE /posts/{id} is a hard delete
 *  and its comments and reactions cascade, so the copy says so — with the
 *  real number when one was handed to us, never a guessed one. */
export function postDeleteConsequence(commentCount?: number): string {
  let removes: string;
  if (commentCount === undefined || commentCount === null || !Number.isFinite(commentCount)) {
    removes = 'the post, its reactions and comments';
  } else if (commentCount <= 0) {
    removes = 'the post and its reactions';
  } else {
    removes = `the post, its reactions and ${commentCount} ${commentCount === 1 ? 'comment' : 'comments'}`;
  }
  return `This permanently removes ${removes}. This can't be undone.`;
}

export default function PostMenu({ postId, onDeleted, commentCount }: PostMenuProps) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState('');
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const handleDelete = async () => {
    setDeleting(true);
    setError('');
    try {
      await apiClient.deletePost(postId);
      setConfirming(false);
      onDeleted(postId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete post');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <>
      <div className="relative" ref={menuRef}>
        <button
          onClick={() => setOpen(!open)}
          className="p-1 rounded-lg hover:bg-surface-elevated transition-colors text-ink-3 hover:text-ink"
          aria-label="Post options"
        >
          <MoreVertical className="w-4 h-4" />
        </button>

        {open && (
          <div className="absolute right-0 top-full mt-1 w-36 bg-surface-overlay border border-edge-md rounded-lg shadow-lg z-10">
            <button
              onClick={() => { setOpen(false); setError(''); setConfirming(true); }}
              className="w-full text-left px-4 py-2 text-sm text-red-400 hover:bg-surface-elevated rounded-lg transition-colors"
            >
              Delete
            </button>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirming}
        title="Delete post?"
        confirmLabel="Delete"
        danger
        busy={deleting}
        error={error || null}
        onConfirm={handleDelete}
        onCancel={() => { setConfirming(false); setError(''); }}
      >
        <p>{postDeleteConsequence(commentCount)}</p>
      </ConfirmDialog>
    </>
  );
}
