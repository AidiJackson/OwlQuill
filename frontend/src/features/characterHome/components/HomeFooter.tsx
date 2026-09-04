/**
 * The quiet close of a public Character Home.
 *
 * Deliberately not a conversion surface. Registration is invite-gated, so a
 * "create your character" call to action would walk a stranger into a wall —
 * worse than saying nothing. What is left is a statement of fact: this
 * character has a home, and the place it lives is in closed beta.
 *
 * The wordmark is text, not a link. Every route on this site except this page
 * sits behind `ProtectedRoute`, so linking anywhere would bounce a logged-out
 * visitor to `/login` from a page that never asked them to sign in. It becomes
 * a link when there is somewhere public to send them.
 */
export default function HomeFooter({ characterName }: { characterName: string }) {
  return (
    <footer className="border-t border-edge mt-16">
      <div className="max-w-[1000px] mx-auto px-4 sm:px-8 py-10 text-center space-y-1.5">
        <p className="font-serif text-base sm:text-lg text-ink-2">
          {characterName} has a home on Ficshon.
        </p>
        <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-3">
          Ficshon is currently in closed beta
        </p>
      </div>
    </footer>
  );
}
