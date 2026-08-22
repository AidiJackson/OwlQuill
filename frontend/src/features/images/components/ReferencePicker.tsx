// Hand-pick up to four of a character's own images as generation references.
//
// These AUGMENT canon — they never replace it. Canon stays the authoritative
// answer to who the character is; a reference here is supporting evidence for
// one image. The server enforces that (canon references are sent first and are
// never trimmed to make room), and the copy below says so plainly, because a
// founder who believes a reference overrides identity will pick the wrong ones.
//
// Only ordinary media is selectable: uploads and previously generated output.
// Canon cards are deliberately absent — which of those reaches the provider is
// the reference router's decision, made from locked canon.
//
// Tablet notes: the grid is 3-up on the narrowest phones and 4-up from `sm`,
// tiles are large tap targets rather than hover-revealed controls, and the role
// selector is a native <select> so iPadOS renders its own wheel picker.
import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, ImageOff, Layers, RefreshCw, Trash2, X } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { LibraryImage } from '@/lib/types';
import {
  MAX_REFERENCES,
  REFERENCE_ROLES,
  REFERENCE_ROLE_LABELS,
  SELECTABLE_REFERENCE_KINDS,
  type ReferenceRole,
  type SelectedReference,
} from '@/features/images/referenceKinds';

interface Props {
  characterId: number | null;
  selected: SelectedReference[];
  onChange: (next: SelectedReference[]) => void;
  disabled?: boolean;
  /** Bumped by the parent after an upload so the grid refetches. */
  refreshToken?: number;
}

export default function ReferencePicker({
  characterId,
  selected,
  onChange,
  disabled = false,
  refreshToken = 0,
}: Props) {
  const [images, setImages] = useState<LibraryImage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (characterId == null) {
      setImages([]);
      setError('');
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError('');
    apiClient
      .listMyCharacterImages({
        characterId,
        kind: [...SELECTABLE_REFERENCE_KINDS],
        sort: 'newest',
        limit: 60,
      })
      .then((rows) => {
        if (!cancelled) setImages(rows);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load images');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    // Guards against a stale response from the previous character landing after
    // a fast switch and repopulating the grid with the wrong character's media.
    return () => {
      cancelled = true;
    };
  }, [characterId, refreshToken]);

  const selectedIds = useMemo(() => new Set(selected.map((s) => s.image.id)), [selected]);
  const atLimit = selected.length >= MAX_REFERENCES;

  // Uploads are deletable from here because here is the only place they are
  // shown — they are not gallery kinds, so the library grid (which owns delete
  // for generated output) never lists them. Without this, uploading would be a
  // one-way door. Generated images are deliberately NOT deletable from the
  // picker: they belong to the grid, which already has that control plus the
  // confirmation and lightbox context that go with it.
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  async function removeUpload(image: LibraryImage) {
    if (characterId == null) return;
    setDeletingId(image.id);
    try {
      await apiClient.deleteCharacterImage(characterId, image.id);
      if (!mountedRef.current) return;
      setImages((prev) => prev.filter((i) => i.id !== image.id));
      // A deleted image must not remain staged as a reference — the server
      // would refuse it at submission, and the founder would not know why.
      onChange(selected.filter((s) => s.image.id !== image.id));
    } catch (err) {
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : 'Could not delete that image');
      }
    } finally {
      if (mountedRef.current) {
        setDeletingId(null);
        setConfirmDeleteId(null);
      }
    }
  }

  function toggle(image: LibraryImage) {
    if (disabled) return;
    if (selectedIds.has(image.id)) {
      onChange(selected.filter((s) => s.image.id !== image.id));
      return;
    }
    if (atLimit) return;
    onChange([...selected, { image, role: 'unspecified' }]);
  }

  function setRole(imageId: number, role: ReferenceRole) {
    onChange(selected.map((s) => (s.image.id === imageId ? { ...s, role } : s)));
  }

  if (characterId == null) return null;

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <Layers className="w-3.5 h-3.5 text-gem" />
          <span className="text-sm font-medium text-ink-2">Reference images</span>
        </div>
        <span className="text-xs text-ink-3">
          {selected.length} of {MAX_REFERENCES} selected
        </span>
      </div>

      <p className="text-xs leading-relaxed text-ink-3">
        Optional. These are sent to the model alongside this character&apos;s canon as extra
        visual evidence — canon still defines who the character is.
      </p>

      {/* Chosen references, with their roles. Above the grid so the founder's
          current selection stays visible while they scroll for more. */}
      {selected.length > 0 && (
        <ul className="space-y-2">
          {selected.map((sel, i) => (
            <li
              key={sel.image.id}
              className="flex items-center gap-3 rounded-xl border border-edge-md bg-surface-elevated p-2"
            >
              <span className="w-6 shrink-0 text-center font-mono text-[11px] text-ink-3">
                {i + 1}
              </span>
              <img
                src={sel.image.url}
                alt=""
                className="w-12 h-12 rounded-lg object-cover shrink-0 bg-surface"
              />
              <label className="sr-only" htmlFor={`ref-role-${sel.image.id}`}>
                Role for reference {i + 1}
              </label>
              <select
                id={`ref-role-${sel.image.id}`}
                className="flex-1 min-w-0 bg-surface border border-edge-md rounded-lg text-sm text-ink-2 px-2 py-2 focus:outline-none focus:border-gem"
                value={sel.role}
                disabled={disabled}
                onChange={(e) => setRole(sel.image.id, e.target.value as ReferenceRole)}
              >
                {REFERENCE_ROLES.map((role) => (
                  <option key={role} value={role}>
                    {REFERENCE_ROLE_LABELS[role]}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => toggle(sel.image)}
                disabled={disabled}
                aria-label={`Remove reference ${i + 1}`}
                className="shrink-0 p-2 rounded-lg text-ink-3 hover:text-ink hover:bg-surface transition-colors disabled:opacity-40"
              >
                <X className="w-4 h-4" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {loading && (
        <p className="flex items-center gap-2 text-xs text-ink-3">
          <RefreshCw className="w-3 h-3 animate-spin" />
          Loading this character&apos;s images…
        </p>
      )}

      {error && <p className="text-xs text-amber-400">{error}</p>}

      {!loading && !error && images.length === 0 && (
        <p className="flex items-center gap-2 text-xs text-ink-3 rounded-xl border border-dashed border-edge-md px-3 py-4">
          <ImageOff className="w-3.5 h-3.5 shrink-0" />
          No images yet for this character. Upload one, or generate an image first.
        </p>
      )}

      {images.length > 0 && (
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
          {images.map((img) => {
            const isSelected = selectedIds.has(img.id);
            const blocked = !isSelected && atLimit;
            const isUpload = img.kind === 'uploaded';
            const confirming = confirmDeleteId === img.id;
            return (
              <div key={img.id} className="relative aspect-square">
                <button
                  type="button"
                  onClick={() => toggle(img)}
                  disabled={disabled || blocked}
                  aria-pressed={isSelected}
                  title={
                    blocked
                      ? `Remove one to select another (limit ${MAX_REFERENCES})`
                      : img.prompt_summary || img.kind.replace(/_/g, ' ')
                  }
                  className={`w-full h-full rounded-xl overflow-hidden border-2 transition-colors ${
                    isSelected ? 'border-gem' : 'border-transparent hover:border-edge-md'
                  } ${blocked ? 'opacity-35' : ''} disabled:cursor-not-allowed`}
                >
                  <img src={img.url} alt="" className="w-full h-full object-cover bg-surface" />
                </button>

                {isSelected && (
                  <span className="pointer-events-none absolute top-1 left-1 w-5 h-5 rounded-full bg-gem text-gem-ink flex items-center justify-center">
                    <Check className="w-3 h-3" />
                  </span>
                )}

                {isUpload && (
                  <>
                    <span className="pointer-events-none absolute bottom-0 inset-x-0 bg-black/60 text-[10px] text-white/80 py-0.5 text-center rounded-b-xl">
                      Uploaded
                    </span>
                    {/* Always visible, not hover-revealed: there is no hover on
                        a tablet, which is the device this is built for. */}
                    <button
                      type="button"
                      disabled={disabled || deletingId === img.id}
                      onClick={() => (confirming ? removeUpload(img) : setConfirmDeleteId(img.id))}
                      onBlur={() => setConfirmDeleteId((c) => (c === img.id ? null : c))}
                      aria-label={confirming ? 'Confirm delete upload' : 'Delete upload'}
                      className={`absolute top-1 right-1 rounded-lg p-1.5 transition-colors disabled:opacity-40 ${
                        confirming
                          ? 'bg-red-600 text-white'
                          : 'bg-black/55 text-white/70 hover:text-white'
                      }`}
                    >
                      {deletingId === img.id ? (
                        <RefreshCw className="w-3 h-3 animate-spin" />
                      ) : (
                        <Trash2 className="w-3 h-3" />
                      )}
                    </button>
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
