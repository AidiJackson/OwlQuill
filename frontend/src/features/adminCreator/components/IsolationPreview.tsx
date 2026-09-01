// "Original → what the model receives", for one feature card.
//
// A feature reference is not sent as the founder sees it: the donor's face is
// suppressed so only the selected feature survives as identity evidence. That
// is invisible without this control, and invisible image processing on someone
// else's photograph is exactly the kind of thing that should be inspectable
// before it is paid for.
//
// Deliberately minimal for this gate: a toggle and an image. It re-derives on
// the server through the same transform generation uses, so what is shown here
// cannot drift from what is sent, and no derived copy is ever stored.
import { useEffect, useState } from 'react';
import { Eye, EyeOff, RefreshCw } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { AdminCreatorRole } from '@/features/adminCreator/referenceRoles';

interface Props {
  characterId: number;
  imageId: number;
  role: AdminCreatorRole;
  disabled?: boolean;
}

export default function IsolationPreview({ characterId, imageId, role, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // Changing the picture or the role invalidates whatever is on screen: the
  // derived image is a function of both.
  useEffect(() => {
    setOpen(false);
    setError('');
  }, [imageId, role]);

  // Object URLs are revoked on replacement and on unmount — without this a
  // board being iterated on leaks a blob per preview.
  useEffect(() => {
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [url]);

  async function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (url || loading) return;
    setLoading(true);
    setError('');
    try {
      setUrl(await apiClient.fetchIsolatedReference(characterId, imageId, role));
    } catch (e) {
      // The server's message says what to do about it; it is not replaced with
      // a generic failure.
      setError(e instanceof Error ? e.message : 'Could not isolate this reference.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-1">
      <button
        type="button"
        onClick={toggle}
        disabled={disabled}
        className="w-full flex items-center justify-center gap-1 rounded-lg border border-edge-md px-2 py-1 text-[10px] text-ink-3 hover:text-ink hover:border-gem/40 transition-colors disabled:opacity-40"
      >
        {loading ? (
          <RefreshCw className="w-3 h-3 animate-spin" />
        ) : open ? (
          <EyeOff className="w-3 h-3" />
        ) : (
          <Eye className="w-3 h-3" />
        )}
        {open ? 'Hide isolated' : 'What the model sees'}
      </button>

      {open && url && (
        <div className="rounded-lg overflow-hidden border border-gem/30 bg-surface">
          <img src={url} alt="" className="w-full block" />
        </div>
      )}
      {open && error && <p className="text-[10px] leading-snug text-amber-400">{error}</p>}
    </div>
  );
}
