import { useState, useEffect } from 'react';
import { X } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { Realm } from '@/lib/types';
import type { CharacterImageRead } from '@/features/characterCreation/shared/types';
import { resolveImageUrl } from '@/features/characterCreation/shared/api';

interface Props {
  open: boolean;
  onClose: () => void;
  preloadedImage?: CharacterImageRead | null;
}

export default function PostComposer({ open, onClose, preloadedImage }: Props) {
  const [content, setContent] = useState('');
  const [contentType, setContentType] = useState<'ooc' | 'ic' | 'narration'>('ooc');
  const [commonsRealm, setCommonsRealm] = useState<Realm | null>(null);
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!open) return;
    setContent('');
    setContentType('ooc');
    setError('');
    setDone(false);
    apiClient
      .getRealms()
      .then((realms) => setCommonsRealm(realms.find((r) => r.is_commons) ?? null))
      .catch(() => {});
  }, [open]);

  const handleSubmit = async () => {
    if (!commonsRealm || !content.trim()) return;
    setPosting(true);
    setError('');
    try {
      await apiClient.createPost(commonsRealm.id, {
        content: content.trim(),
        content_type: contentType,
        ...(preloadedImage ? { image_url: resolveImageUrl(preloadedImage.url) } : {}),
      });
      setDone(true);
      setTimeout(onClose, 800);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create post.');
    } finally {
      setPosting(false);
    }
  };

  if (!open) return null;

  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-50" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4">
        <div
          className="bg-surface border border-edge rounded-xl w-full max-w-lg shadow-xl space-y-4 p-5"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-ink">New Post</h3>
            <button
              type="button"
              onClick={onClose}
              className="text-ink-3 hover:text-ink-2 p-1 rounded transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {preloadedImage && (
            <div className="rounded-lg overflow-hidden border border-edge bg-black flex items-center justify-center max-h-56">
              <img
                src={resolveImageUrl(preloadedImage.url)}
                alt="Attached image"
                className="max-h-56 object-contain"
              />
            </div>
          )}

          <textarea
            className="textarea w-full"
            rows={4}
            placeholder="What's on your mind?"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            disabled={posting || done}
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus
          />

          <div className="flex items-center gap-2">
            {(['ooc', 'ic', 'narration'] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setContentType(t)}
                className={`text-xs px-2.5 py-1 rounded transition-colors ${
                  contentType === t
                    ? 'bg-gem text-white'
                    : 'bg-surface-elevated text-ink-2 hover:bg-surface-overlay hover:text-ink'
                }`}
              >
                {t.toUpperCase()}
              </button>
            ))}
          </div>

          {error && (
            <p className="text-sm text-red-400 bg-red-400/10 rounded-lg px-3 py-2">{error}</p>
          )}

          <div className="flex gap-3">
            <button
              type="button"
              onClick={onClose}
              className="btn btn-secondary text-sm flex-1"
              disabled={posting}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!content.trim() || posting || done || !commonsRealm}
              className="btn btn-primary text-sm flex-1 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {done ? 'Posted!' : posting ? 'Posting…' : 'Post'}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
