// InlineNotice — the one way a page tells the user something happened.
//
// Polish Phase 0 (D1). Ficshon already had an inline-notice *style* — the
// amber "text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2" paragraph
// that most pages hand-roll for errors — and, alongside it, eleven native
// `alert()` calls that dropped the user into browser chrome for "Successfully
// joined realm!" and "Failed to delete draft." This component is that existing
// style given a name, with the three tones the pages actually needed, so the
// alerts could be replaced without inventing a toast system.
//
// Deliberately NOT a toast: it renders where the page puts it, it does not
// stack, it does not time out on its own, and it has no portal. A page that
// wants a message to disappear passes `onDismiss` and clears its own state.
import type { ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react';

export type NoticeTone = 'info' | 'success' | 'warning' | 'error';

interface Props {
  tone?: NoticeTone;
  children: ReactNode;
  /** When given, a small close control is shown and calls this. */
  onDismiss?: () => void;
  className?: string;
}

const TONE_CLASSES: Record<NoticeTone, string> = {
  info: 'text-ink-2 bg-surface-elevated border-edge-md',
  success: 'text-gem bg-gem-soft border-gem/30',
  warning: 'text-amber-400/90 bg-amber-400/10 border-amber-400/20',
  error: 'text-red-400 bg-red-400/10 border-red-400/20',
};

const TONE_ICON: Record<NoticeTone, typeof Info> = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: XCircle,
};

export default function InlineNotice({ tone = 'info', children, onDismiss, className = '' }: Props) {
  const Icon = TONE_ICON[tone];
  return (
    <div
      role={tone === 'error' || tone === 'warning' ? 'alert' : 'status'}
      className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${TONE_CLASSES[tone]} ${className}`}
    >
      <Icon className="w-4 h-4 shrink-0 mt-0.5" />
      <div className="min-w-0 flex-1">{children}</div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 -mr-1 p-0.5 rounded opacity-70 hover:opacity-100 transition-opacity"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}
