// The reference board: four fixed cards, filled independently.
//
// Admin Creator's primary reference interface, and the thing that distinguishes
// it from the Image Generator's browse-and-select gallery. Each card is either
// empty — offering "Choose from Library" and "Upload" — or holds one image with
// its role, source badge, replace and remove controls. Any mix of library media
// and device uploads, in any combination, with empty cards allowed.
//
// Card order is meaningful and is preserved end to end. Admin Creator submits
// reference_mode="deliberate", so these cards are the ONLY reference images the
// provider receives, in card order — no canon face, body, anchor or accessory
// reference is added behind them, and the scene router is never consulted. A
// card is only ever dropped if the provider itself takes fewer images than the
// founder filled. Cards therefore never shift up when one is cleared.
//
// The selected character is an ownership and storage destination: it scopes
// which library images can be picked and owns the generated row. It does not
// contribute to the image, and nothing here writes to canon.
//
// The /images Image Generator is unaffected: it sends no mode and keeps the
// canon-driven policy it has always had.
//
// Only ordinary media is selectable: uploads and previously generated output.
// Canon cards are deliberately absent — this workflow does not draw on canon at
// all, so there is nothing for them to be picked into.
//
// All slot rules live in referenceSlots.ts so they can be pinned by tests; this
// component renders their output and owns no selection logic of its own.
import { useState } from 'react';
import { ImagePlus, Layers, Repeat2, X } from 'lucide-react';
import type { LibraryImage } from '@/lib/types';
import { MAX_REFERENCES } from '@/features/images/referenceKinds';
import {
  ROLE_GROUPS,
  ROLE_HINTS,
  isFeatureRole,
  roleLabel,
  type AdminCreatorRole,
} from '@/features/adminCreator/referenceRoles';
import IsolationPreview from '@/features/adminCreator/components/IsolationPreview';
import {
  clearSlot,
  fillSlot,
  filledCount,
  normalizeSlots,
  removeImage,
  setSlotRole,
  slotSource,
  usedImageIds,
  type ReferenceSlots,
} from '@/features/adminCreator/referenceSlots';
import ReferenceLibraryModal from '@/features/adminCreator/components/ReferenceLibraryModal';
import ReferenceUploadControl from '@/features/adminCreator/components/ReferenceUploadControl';

interface Props {
  characterId: number | null;
  slots: ReferenceSlots;
  onChange: (next: ReferenceSlots) => void;
  disabled?: boolean;
  /** Bumped by the parent after an upload so the modal refetches. */
  refreshToken?: number;
  /** An upload happened — the parent bumps refreshToken in response. */
  onUploaded?: () => void;
}

export default function ReferenceCardBoard({
  characterId,
  slots,
  onChange,
  disabled = false,
  refreshToken = 0,
  onUploaded,
}: Props) {
  // Which card the library modal is filling. null = closed.
  const [pickingFor, setPickingFor] = useState<number | null>(null);

  const board = normalizeSlots(slots);
  const filled = filledCount(board);
  const used = usedImageIds(board);

  function handleLibrarySelect(image: LibraryImage) {
    if (pickingFor == null) return;
    onChange(fillSlot(board, pickingFor, image));
    setPickingFor(null);
  }

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <Layers className="w-3.5 h-3.5 text-gem" />
          <span className="text-sm font-medium text-ink-2">Reference images</span>
        </div>
        <span className="text-xs text-ink-3">
          {filled} of {MAX_REFERENCES} used
        </span>
      </div>

      <p className="text-xs leading-relaxed text-ink-3">
        These are the only reference images sent to the model, in card order. This
        character&apos;s canon is not used here — the character decides which images you can
        pick and where the result is saved, nothing more.
      </p>

      {characterId == null ? (
        <p className="text-xs text-ink-3 rounded-xl border border-dashed border-edge-md px-3 py-6 text-center">
          Select a character to choose references.
        </p>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3">
          {board.map((slot, index) => (
            <div
              key={index}
              className="rounded-xl border border-edge-md bg-surface-elevated/60 p-2 flex flex-col gap-2"
            >
              <div className="flex items-center justify-between gap-1">
                <span className="font-mono text-[11px] text-ink-3">{index + 1}</span>
                {slot && (
                  <span className="rounded-md bg-surface px-1.5 py-0.5 text-[10px] text-ink-3">
                    {slotSource(slot) === 'upload' ? 'Uploaded' : 'Library'}
                  </span>
                )}
              </div>

              {slot ? (
                <>
                  <div className="relative aspect-square rounded-lg overflow-hidden bg-surface">
                    <img
                      src={slot.image.url}
                      alt=""
                      className="w-full h-full object-cover"
                      title={slot.image.prompt_summary || slot.image.kind.replace(/_/g, ' ')}
                    />
                  </div>

                  <label className="sr-only" htmlFor={`ac-ref-role-${index}`}>
                    What reference {index + 1} represents
                  </label>
                  <select
                    id={`ac-ref-role-${index}`}
                    className="w-full min-w-0 bg-surface border border-edge-md rounded-lg text-xs text-ink-2 px-2 py-1.5 focus:outline-none focus:border-gem"
                    value={slot.role}
                    disabled={disabled}
                    onChange={(e) =>
                      onChange(setSlotRole(board, index, e.target.value as AdminCreatorRole))
                    }
                  >
                    {/* Grouped, because sixteen flat options is a scroll and a
                        guess. The groups are presentation only — the value sent
                        is unchanged, and ADMIN_CREATOR_ROLES remains the one
                        list every other module reads. */}
                    {ROLE_GROUPS.map((group) => (
                      <optgroup key={group.label} label={group.label}>
                        {group.roles.map((value) => (
                          <option key={value} value={value}>
                            {roleLabel(value)}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>

                  {/* What this selection actually authorises. Without it the
                      difference between "Clothing" and "Character 1" is a guess,
                      and the wrong guess is what put a rolled sleeve on a suit. */}
                  <p className="text-[10px] leading-snug text-ink-3">{ROLE_HINTS[slot.role]}</p>

                  {/* Feature references are transformed before they reach the
                      provider. This is the only way to see that happen. */}
                  {isFeatureRole(slot.role) && characterId != null && (
                    <IsolationPreview
                      characterId={characterId}
                      imageId={slot.image.id}
                      role={slot.role}
                      disabled={disabled}
                    />
                  )}

                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => setPickingFor(index)}
                      disabled={disabled}
                      aria-label={`Replace reference ${index + 1}`}
                      className="flex-1 flex items-center justify-center gap-1 rounded-lg border border-edge-md px-2 py-1.5 text-[11px] text-ink-3 hover:text-ink hover:border-gem/40 transition-colors disabled:opacity-40"
                    >
                      <Repeat2 className="w-3.5 h-3.5" />
                      Replace
                    </button>
                    <button
                      type="button"
                      onClick={() => onChange(clearSlot(board, index))}
                      disabled={disabled}
                      aria-label={`Remove reference ${index + 1}`}
                      className="shrink-0 rounded-lg border border-edge-md p-1.5 text-ink-3 hover:text-ink hover:border-gem/40 transition-colors disabled:opacity-40"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <div className="aspect-square rounded-lg border border-dashed border-edge-md flex items-center justify-center text-ink-3">
                    <ImagePlus className="w-5 h-5 opacity-60" />
                  </div>
                  <button
                    type="button"
                    onClick={() => setPickingFor(index)}
                    disabled={disabled}
                    className="w-full rounded-xl border border-edge-md bg-surface-elevated px-2 py-1.5 text-xs text-ink-2 hover:text-ink hover:border-gem/40 transition-colors disabled:opacity-50"
                  >
                    Choose from Library
                  </button>
                  <ReferenceUploadControl
                    characterId={characterId}
                    disabled={disabled}
                    onUploaded={(image) => {
                      // The upload lands in the card it was started from — that
                      // is what was being aimed at when the control was tapped.
                      onChange(fillSlot(board, index, image));
                      onUploaded?.();
                    }}
                  />
                </>
              )}
            </div>
          ))}
        </div>
      )}

      <ReferenceLibraryModal
        open={pickingFor != null}
        characterId={characterId}
        slotIndex={pickingFor}
        usedImageIds={used}
        onSelect={handleLibrarySelect}
        onClose={() => setPickingFor(null)}
        refreshToken={refreshToken}
        onImageDeleted={(imageId) => onChange(removeImage(board, imageId))}
      />
    </div>
  );
}
