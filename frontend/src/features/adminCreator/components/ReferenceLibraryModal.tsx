// Pick ONE image from this character's eligible library, for one reference card.
//
// Opened from a specific card and closes on selection, so the founder's mental
// model stays "this card gets that picture" rather than "assemble a set". The
// generator no longer shows a browse-everything grid; this modal is where the
// library is browsed, one card at a time.
//
// Only ordinary media is listed: uploads and previously generated output. Canon
// cards are deliberately absent — which of those reaches the provider is the
// reference router's decision, made from locked canon, and a hand-picked path
// into the same payload would blur that boundary.
//
// Character 2 (Phase 0B): a card in the Character 2 bucket is, by definition, a
// different person from the selected character, so when the card being filled
// carries that role the modal offers a "Whose library?" selector over the
// founder's OTHER characters. The listing then comes from that character —
// same endpoint, same eligible kinds, same ownership check server-side. Every
// other role keeps the selected character's library and nothing else; this is
// not a multi-character browser. The server re-validates the pick under the
// same rule (`manual_references._row_in_scope`), so the selector decides what
// is OFFERED, never what is allowed.
//
// Deleting an upload lives here because here is the only place uploads are
// shown: they are not gallery kinds, so the main library grid never lists them.
// Without this control, uploading would be a one-way door. Generated images are
// deliberately NOT deletable from here — they belong to the library grid, which
// already has that control plus its confirmation and lightbox context.
//
// Tablet notes: 2-up on the narrowest phones and 4-up from `sm`, tiles are large
// tap targets, and controls are always visible rather than hover-revealed —
// there is no hover on the device this is built for.
import { useEffect, useRef, useState } from 'react';
import { ImageOff, RefreshCw, Trash2, X } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { Character, LibraryImage } from '@/lib/types';
import { SELECTABLE_REFERENCE_KINDS } from '@/features/images/referenceKinds';
import type { AdminCreatorRole } from '@/features/adminCreator/referenceRoles';

interface Props {
  open: boolean;
  characterId: number | null;
  /** Which card is being filled — shown in the title so the target is never ambiguous. */
  slotIndex: number | null;
  /** The role of the card being filled, or null for an empty card. Only
   *  `character_2` changes anything: it unlocks the source-character selector. */
  slotRole?: AdminCreatorRole | null;
  /** Every character this account owns — the Character 2 selector's options.
   *  The server lists only owned libraries regardless of what is passed here. */
  characters?: readonly Character[];
  /** Ids already on the board; offered but marked, since picking one MOVES it. */
  usedImageIds: Set<number>;
  onSelect: (image: LibraryImage) => void;
  onClose: () => void;
  /** Bumped by the parent after an upload so the list refetches. */
  refreshToken?: number;
  /** An upload was deleted — the parent must unstage it from any card. */
  onImageDeleted?: (imageId: number) => void;
}

export default function ReferenceLibraryModal({
  open,
  characterId,
  slotIndex,
  slotRole = null,
  characters = [],
  usedImageIds,
  onSelect,
  onClose,
  refreshToken = 0,
  onImageDeleted,
}: Props) {
  const [images, setImages] = useState<LibraryImage[]>([]);
  // Whose library is listed. Always the selected character unless this is a
  // Character 2 card and the founder has chosen another of their characters.
  const [sourceCharacterId, setSourceCharacterId] = useState<number | null>(characterId);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Escape closes, matching every other dismissible surface in the app.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const isCharacter2 = slotRole === 'character_2';
  const otherCharacters = characters.filter((c) => c.id !== characterId);
  // The selector is only worth showing when there is somewhere else to look.
  const showSourceSelector = isCharacter2 && otherCharacters.length > 0;
  const selectedCharacter = characters.find((c) => c.id === characterId) ?? null;
  const sourceCharacterName =
    characters.find((c) => c.id === sourceCharacterId)?.name ?? null;

  // Every open starts from the selected character's own library. A choice made
  // for one card must not leak into the next card, and a non-Character-2 card
  // must never inherit another character's listing.
  useEffect(() => {
    if (open) setSourceCharacterId(characterId);
  }, [open, characterId, slotRole]);

  useEffect(() => {
    if (!open || characterId == null || sourceCharacterId == null) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    apiClient
      .listMyCharacterImages({
        characterId: sourceCharacterId,
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
    // a fast switch and listing the wrong character's media.
    return () => {
      cancelled = true;
    };
  }, [open, characterId, sourceCharacterId, refreshToken]);

  async function removeUpload(image: LibraryImage) {
    if (sourceCharacterId == null) return;
    setDeletingId(image.id);
    try {
      await apiClient.deleteCharacterImage(sourceCharacterId, image.id);
      if (!mountedRef.current) return;
      setImages((prev) => prev.filter((i) => i.id !== image.id));
      onImageDeleted?.(image.id);
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

  if (!open || characterId == null) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/70 p-0 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-label="Choose a reference image"
      onClick={onClose}
    >
      <div
        className="w-full sm:max-w-3xl max-h-[85vh] flex flex-col rounded-t-2xl sm:rounded-2xl border border-edge-md bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-edge-md px-4 py-3 shrink-0">
          <div className="min-w-0">
            <h2 className="text-sm font-medium text-ink-2">
              Choose an image{slotIndex != null ? ` for reference ${slotIndex + 1}` : ''}
            </h2>
            <p className="text-xs text-ink-3 mt-0.5">
              {sourceCharacterName
                ? `${sourceCharacterName}’s uploads and generated images.`
                : 'This character’s uploads and generated images.'}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 p-2 rounded-lg text-ink-3 hover:text-ink hover:bg-surface transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {showSourceSelector && (
          <div className="border-b border-edge-md px-4 py-3 shrink-0 space-y-1.5">
            <label className="block text-xs font-medium text-ink-2" htmlFor="ac-ref-source">
              Character 2 · whose library?
            </label>
            <select
              id="ac-ref-source"
              className="w-full bg-surface border border-edge-md rounded-lg text-sm text-ink-2 px-3 py-2 focus:outline-none focus:border-gem"
              value={sourceCharacterId ?? ''}
              onChange={(e) => setSourceCharacterId(Number(e.target.value))}
            >
              {selectedCharacter && (
                <option value={selectedCharacter.id}>
                  {selectedCharacter.name} (this character)
                </option>
              )}
              {otherCharacters.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <p className="text-[11px] leading-snug text-ink-3">
              A second, different person — pick them from another of your characters. Only
              Character 2 cards may do this; the result is still saved to{' '}
              {selectedCharacter?.name ?? 'the selected character'}.
            </p>
          </div>
        )}

        <div className="overflow-y-auto p-4 space-y-3">
          {loading && (
            <p className="flex items-center gap-2 text-xs text-ink-3">
              <RefreshCw className="w-3 h-3 animate-spin" />
              Loading images…
            </p>
          )}

          {error && <p className="text-xs text-amber-400">{error}</p>}

          {!loading && !error && images.length === 0 && (
            <p className="flex items-center gap-2 text-xs text-ink-3 rounded-xl border border-dashed border-edge-md px-3 py-6">
              <ImageOff className="w-3.5 h-3.5 shrink-0" />
              No eligible images yet for {sourceCharacterName ?? 'this character'}. Upload one,
              or generate an image first.
            </p>
          )}

          {images.length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {images.map((img) => {
                const inUse = usedImageIds.has(img.id);
                const isUpload = img.kind === 'uploaded';
                const confirming = confirmDeleteId === img.id;
                return (
                  <div key={img.id} className="relative aspect-square">
                    <button
                      type="button"
                      onClick={() => onSelect(img)}
                      title={img.prompt_summary || img.kind.replace(/_/g, ' ')}
                      className={`w-full h-full rounded-xl overflow-hidden border-2 transition-colors ${
                        inUse ? 'border-gem' : 'border-transparent hover:border-edge-md'
                      }`}
                    >
                      <img src={img.url} alt="" className="w-full h-full object-cover bg-surface" />
                    </button>

                    {inUse && (
                      <span className="pointer-events-none absolute top-1 left-1 rounded-md bg-gem px-1.5 py-0.5 text-[10px] font-medium text-gem-ink">
                        In use
                      </span>
                    )}

                    {isUpload && (
                      <>
                        <span className="pointer-events-none absolute bottom-0 inset-x-0 bg-black/60 text-[10px] text-white/80 py-0.5 text-center rounded-b-xl">
                          Uploaded
                        </span>
                        <button
                          type="button"
                          disabled={deletingId === img.id}
                          onClick={() =>
                            confirming ? removeUpload(img) : setConfirmDeleteId(img.id)
                          }
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
      </div>
    </div>
  );
}
