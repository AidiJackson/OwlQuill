import { X } from 'lucide-react';

/**
 * The persistent status marker, laid over the top of the cover.
 *
 * Plain text, never a link: every other route sits behind a guard, so the
 * wordmark has nowhere public to go. Deliberately smaller and quieter than
 * anything in the hero — it says where the visitor is, not who they are
 * looking at. Readable over any cover because it carries its own backdrop.
 */
export function ClosedBetaMarker() {
  return (
    <div
      className="absolute inset-x-0 top-0 z-10 pointer-events-none"
      style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}
    >
      <div className="max-w-[1000px] mx-auto px-4 sm:px-8 pt-4 sm:pt-5">
        {/* Same left edge as the hero's name, which pulls left on wide screens. */}
        <div className="xl:-ml-10 2xl:-ml-16">
          <p className="inline-flex items-center gap-2 rounded-full bg-app border border-edge shadow-sm px-3 py-1">
            <span className="font-serif text-sm text-ink">Ficshon</span>
            <span aria-hidden="true" className="text-ink-3">&middot;</span>
            <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink-2">
              Closed beta
            </span>
          </p>
        </div>
      </div>
    </div>
  );
}

/**
 * The first-arrival welcome.
 *
 * IN FLOW, directly beneath the hero — not a modal, not an overlay, not a
 * toast. It never covers the character, never blocks scrolling, never takes
 * focus, and a visitor meets the character before they meet the explanation.
 *
 * A labelled `aside`, not a live region: it is page content read in order, so
 * nothing is announced on arrival and nothing lingers after dismissal.
 *
 * No call to action, by design: there is nothing here to join, browse or
 * sign in to. The social context beneath each post is what shows the world.
 */
export function OrientationCard({ onDismiss }: { onDismiss: () => void }) {
  return (
    <aside
      aria-labelledby="ficshon-orientation-title"
      className="relative max-w-3xl rounded-xl border border-edge bg-surface pl-4 pr-12 py-4 sm:pl-5 sm:py-5 border-l-2 border-l-gem/60"
    >
      <h2 id="ficshon-orientation-title" className="font-serif text-base sm:text-lg text-ink">
        Welcome to Ficshon
      </h2>
      <p className="mt-1.5 text-sm sm:text-[15px] leading-relaxed text-ink-2">
        You&rsquo;ve stepped into a world of characters, stories and roleplay. Ficshon is
        currently in closed beta &mdash; and you&rsquo;re meeting one of its characters.
      </p>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss welcome"
        className="absolute top-2 right-2 inline-flex items-center justify-center w-10 h-10 rounded-lg text-ink-3 hover:text-ink hover:bg-surface-elevated transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-gem/60"
      >
        <X className="w-4 h-4" aria-hidden="true" />
      </button>
    </aside>
  );
}
