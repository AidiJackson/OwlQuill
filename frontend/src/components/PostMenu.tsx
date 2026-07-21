import { useState, useRef, useEffect } from 'react';
import { MoreVertical } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';

interface PostMenuProps {
  postId: number;
  onDeleted: (postId: number) => void;
}

export default function PostMenu({ postId, onDeleted }: PostMenuProps) {
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
      onDeleted(postId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete post');
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
              onClick={() => { setOpen(false); setConfirming(true); }}
              className="w-full text-left px-4 py-2 text-sm text-red-400 hover:bg-surface-elevated rounded-lg transition-colors"
            >
              Delete
            </button>
          </div>
        )}
      </div>

      {/* Confirm modal */}
      {confirming && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-surface-overlay border border-edge-md rounded-xl max-w-sm w-full p-6">
            <h3 className="text-lg font-semibold text-ink mb-2">Delete post?</h3>
            <p className="text-ink-2 text-sm mb-5">This can't be undone.</p>

            {error && (
              <p className="text-red-400 text-sm mb-3">{error}</p>
            )}

            <div className="flex justify-end gap-3">
              <button
                onClick={() => { setConfirming(false); setError(''); }}
                className="btn btn-secondary text-sm"
                disabled={deleting}
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="px-4 py-2 text-sm font-medium rounded-lg bg-red-600 text-white hover:bg-red-500 transition-colors disabled:opacity-50"
              >
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
