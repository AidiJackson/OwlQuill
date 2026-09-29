/**
 * Shown above a composer that was prefilled by WriteSpace's Continue to
 * publish, so the writer knows where the text came from and how to leave.
 *
 * Back returns to WriteSpace, whose draft and session are untouched. Discard
 * drops only this prepared post; the WriteSpace draft survives either way.
 */
interface Props {
  onBack: () => void;
  onDiscard: () => void;
  disabled?: boolean;
}

export default function WriteSpaceFinaliseBanner({ onBack, onDiscard, disabled }: Props) {
  return (
    <div
      data-testid="writespace-finalise-banner"
      className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 mb-3 rounded-lg border border-gem/25 bg-gem/[0.06] px-3 py-2 text-xs"
    >
      <span className="font-semibold text-gem">From WriteSpace</span>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onBack}
          disabled={disabled}
          className="text-ink-2 hover:text-ink transition-colors disabled:opacity-40"
        >
          Back to WriteSpace
        </button>
        <button
          type="button"
          onClick={onDiscard}
          disabled={disabled}
          className="text-ink-3 hover:text-red-400 transition-colors disabled:opacity-40"
        >
          Discard
        </button>
      </div>
    </div>
  );
}
