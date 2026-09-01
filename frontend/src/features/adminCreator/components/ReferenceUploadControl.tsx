// Compact "Upload" control for one reference card.
//
// Deliberately a small, separate control rather than a variant of
// features/images/components/UploadImageButton: that button belongs to the
// Image Generator, which is a live system we are not changing to accommodate
// this experiment. Admin Creator owning its own control means the two workflows
// can diverge — different copy, different sizing, different affordances —
// without either one editing the other.
//
// It posts to the SAME endpoint and obeys the SAME limits; only the presentation
// differs. The server is the authority on both the size cap and the format, and
// re-checks by sniffing the bytes.
//
// A plain <input type="file"> behind a label: that is what opens the photo
// library / camera on iPadOS and Android, needs no drag-and-drop surface (which
// does not exist on a tablet), and is a tap target rather than a hover
// affordance.
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

export default function ReferenceUploadControl({
  characterId,
  onUploaded,
  disabled = false,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const mountedRef = useRef(true);

  async function handleFiles(files: FileList | null) {
    const file = files?.[0];
    if (!file || characterId == null) return;
    setError('');
    // Checked here only to save a round-trip on an obvious miss; the server
    // re-checks the size AND sniffs the bytes, which is the real gate.
    if (file.size > MAX_BYTES) {
      setError('Over the 10 MB limit.');
      return;
    }
    setBusy(true);
    try {
      const image = await apiClient.uploadCharacterImage(characterId, file);
      if (mountedRef.current) onUploaded(image);
    } catch (err) {
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : 'Upload failed.');
      }
    } finally {
      if (mountedRef.current) setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  }

  const unavailable = disabled || busy || characterId == null;

  return (
    <div>
      <label
        className={`flex items-center justify-center gap-1.5 w-full px-2 py-1.5 rounded-xl border border-edge-md bg-surface-elevated text-xs text-ink-2 transition-colors ${
          unavailable
            ? 'opacity-50 cursor-not-allowed'
            : 'cursor-pointer hover:text-ink hover:border-gem/40'
        }`}
      >
        {busy ? (
          <>
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            Uploading…
          </>
        ) : (
          <>
            <Upload className="w-3.5 h-3.5" />
            Upload
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
      {error && <p className="mt-1 text-[10px] text-amber-400">{error}</p>}
    </div>
  );
}
