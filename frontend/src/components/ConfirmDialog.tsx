// ConfirmDialog — a deliberate yes/no, with an optional type-to-confirm.
//
// Polish Phase 0 (D1 / M2 / X6). Replaces the native `window.confirm()` calls
// and the hand-rolled two-step delete modal. It exists so that every
// destructive action in Ficshon asks the same way: the title names the
// action, the body names the consequence, the confirm button repeats the
// verb, and — for permanent deletions — the user types the thing's name.
//
// Kept small on purpose. Not a general Modal primitive: no children slots
// beyond the body, no size variants, no nesting. If a surface needs a form in
// an overlay, that is a different component and a later phase.
//
// Behaviour that matters and is therefore fixed here rather than per-caller:
//   * Escape and backdrop tap cancel (never confirm);
//   * initial focus lands on Cancel for a danger dialog — the safe default —
//     and on Confirm otherwise;
//   * while `busy`, nothing can dismiss it, so a delete cannot be
//     double-submitted or abandoned mid-flight;
//   * on phones it is a bottom sheet; on wider screens a centred card.
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { Loader2 } from 'lucide-react';
import InlineNotice from '@/components/InlineNotice';

interface Props {
  open: boolean;
  title: string;
  /** The consequence, in plain words. Rendered inside the dialog body. */
  children?: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** Red confirm button, Cancel focused first. */
  danger?: boolean;
  /** When set, the user must type this exact text before Confirm enables. */
  confirmText?: string;
  /** Prompt shown above the type-to-confirm input. */
  confirmTextLabel?: string;
  busy?: boolean;
  /** An error from the last confirm attempt, shown inside the dialog. */
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  cancelLabel = 'Cancel',
  danger = false,
  confirmText,
  confirmTextLabel,
  busy = false,
  error = null,
  onConfirm,
  onCancel,
}: Props) {
  const [typed, setTyped] = useState('');
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  // Reset the typed text every time the dialog opens, so a name typed for one
  // deletion can never pre-satisfy the next.
  useEffect(() => {
    if (open) setTyped('');
  }, [open]);

  useEffect(() => {
    if (!open) return;
    (danger ? cancelRef : confirmRef).current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) onCancel();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, danger, busy, onCancel]);

  if (!open) return null;

  const typedOk = !confirmText || typed.trim() === confirmText.trim();
  const canConfirm = typedOk && !busy;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 p-0 sm:p-4"
      onClick={() => {
        if (!busy) onCancel();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full sm:max-w-md bg-surface-overlay border border-edge-md rounded-t-2xl sm:rounded-2xl p-5 sm:p-6 space-y-4 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id={titleId} className={`text-lg font-semibold ${danger ? 'text-red-400' : 'text-ink'}`}>
          {title}
        </h3>

        {children && <div className="text-sm text-ink-2 space-y-2">{children}</div>}

        {confirmText && (
          <label className="block space-y-1.5">
            <span className="text-xs text-ink-3">
              {confirmTextLabel ?? (
                <>
                  Type <span className="font-semibold text-ink-2">{confirmText}</span> to confirm
                </>
              )}
            </span>
            <input
              type="text"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              disabled={busy}
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              className="input"
              aria-label={`Type ${confirmText} to confirm`}
            />
          </label>
        )}

        {error && <InlineNotice tone="error">{error}</InlineNotice>}

        <div className="flex gap-3 pt-1">
          <button
            ref={cancelRef}
            type="button"
            className="btn btn-secondary flex-1"
            onClick={onCancel}
            disabled={busy}
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            className={`flex-1 inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
              danger ? 'bg-red-600 hover:bg-red-500 text-white' : 'bg-gem hover:bg-gem/90 text-gem-ink'
            }`}
            onClick={onConfirm}
            disabled={!canConfirm}
          >
            {busy && <Loader2 className="w-4 h-4 animate-spin" />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
