// Upload an image from this device as private character media.
//
// Founder/seeder only. Deliberately a plain <input type="file"> behind a label:
// that is what opens the photo library / camera on iPadOS and Android, needs no
// drag-and-drop surface (which does not exist on a tablet), and is a large tap
// target rather than a hover affordance.
//
// The uploaded image is a private REFERENCE. It is not gallery material and is
// not post-attachable — the server enforces both by giving it a kind that is on
// neither allowlist. The copy says so, so a founder does not upload something
// expecting it to appear on the character's public page.
import { useRef, useState } from 'react';
import { RefreshCw, Upload } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { LibraryImage } from '@/lib/types';

/** Mirror of the server's limits — the server is the authority on both. */
const MAX_BYTES = 10 * 1024 * 1024;
const ACCEPT = 'image/png,image/jpeg,image/webp';

interface Props {
  characterId: number | null;
  onUploaded: (image: LibraryImage) => void;
  disabled?: boolean;
}

export default function UploadImageButton({ characterId, onUploaded, disabled = false }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const mountedRef = useRef(true);

  async function handleFiles(files: FileList | null) {
    const file = files?.[0];
    if (!file || characterId == null) return;
    setError('');
    // Checked here only to save the founder a round-trip on an obvious miss;
    // the server re-checks the size AND sniffs the bytes, which is the real gate.
    if (file.size > MAX_BYTES) {
      setError('That image is over the 10 MB limit.');
      return;
    }
    setBusy(true);
    try {
      const image = await apiClient.uploadCharacterImage(characterId, file);
      if (mountedRef.current) onUploaded(image);
    } catch (err) {
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : 'Upload failed. Please try again.');
      }
    } finally {
      if (mountedRef.current) setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  }

  const unavailable = disabled || busy || characterId == null;

  return (
    <div className="space-y-2">
      <label
        className={`flex items-center justify-center gap-2 w-full sm:w-auto px-4 py-3 rounded-xl border border-edge-md bg-surface-elevated text-sm text-ink-2 transition-colors ${
          unavailable
            ? 'opacity-50 cursor-not-allowed'
            : 'cursor-pointer hover:text-ink hover:border-gem/40'
        }`}
      >
        {busy ? (
          <>
            <RefreshCw className="w-4 h-4 animate-spin" />
            Uploading…
          </>
        ) : (
          <>
            <Upload className="w-4 h-4" />
            Upload image
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          disabled={unavailable}
          onChange={(e) => handleFiles(e.target.files)}
        />
      </label>
      <p className="text-xs text-ink-3">
        PNG, JPEG or WebP, up to 10 MB. Stored privately against this character as a
        reference — it doesn&apos;t appear in the public gallery and can&apos;t be attached
        to a post.
      </p>
      {error && <p className="text-xs text-amber-400">{error}</p>}
    </div>
  );
}
