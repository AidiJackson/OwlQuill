import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Lock, Feather, Check } from 'lucide-react';
import { useAuthStore } from '@/lib/store';
import { apiClient } from '@/lib/apiClient';
import { canCreateCharacter } from '@/lib/entitlements';
import type { User } from '@/lib/types';

/**
 * The Writer Unlock gate.
 *
 * Positioned as coming soon, not as something withheld: no unlock path is
 * wired to Ficshon yet, so this screen never implies one can be completed
 * here, and there is no button that quietly grants the entitlement. A Wanderer
 * who lands here — by clicking "Become a Writer" or by typing /characters/new
 * — is told plainly that the unlock isn't available during the closed beta,
 * and stays a Wanderer.
 *
 * The copy deliberately says nothing about how the unlock will be obtained;
 * that is not settled, and speculating here would only invite questions the
 * product cannot answer yet. When the real entry point lands it replaces the
 * notice block below; routing and entitlement checks already hold.
 */
export default function BecomeAWriter() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const entitled = canCreateCharacter(user);

  const [busy, setBusy] = useState(false);
  const [waitlistError, setWaitlistError] = useState('');
  const onWaitlist = !!user?.writer_waitlist_joined_at;

  // Both calls return the refreshed account, so the confirmed state comes from
  // the server rather than from optimistic local guessing.
  const runWaitlist = async (call: () => Promise<User>) => {
    if (busy) return;
    setBusy(true);
    setWaitlistError('');
    try {
      setUser(await call());
    } catch (err) {
      setWaitlistError(
        err instanceof Error ? err.message : 'Could not update your waitlist status.'
      );
    } finally {
      setBusy(false);
    }
  };

  const handleJoin = () => runWaitlist(() => apiClient.joinWriterWaitlist());
  const handleLeave = () => runWaitlist(() => apiClient.leaveWriterWaitlist());

  return (
    <div className="max-w-2xl mx-auto p-6 sm:p-8">
      <div className="flex items-start gap-4 mb-6">
        <div className="w-12 h-12 rounded-2xl bg-gem-soft flex items-center justify-center flex-shrink-0">
          <Feather className="w-6 h-6 text-gem" />
        </div>
        <div>
          <h1 className="font-serif text-3xl font-medium tracking-[-0.02em] text-ink">
            Become a Writer
          </h1>
          <p className="text-sm text-ink-2 mt-1">
            Unlock one character and Ficshon's creator tools.
          </p>
        </div>
      </div>

      <div className="card mb-6 space-y-3">
        <h2 className="text-lg font-semibold">What the Writer Unlock includes</h2>
        <ul className="text-sm text-ink-2 space-y-1.5 list-disc pl-5">
          <li>One character — your public identity across Ficshon</li>
          <li>Posting in the Commons and in Realms</li>
          <li>StoryLab, Editor Studio and RP stories</li>
          <li>Character image generation and the Image Library</li>
          <li>Story Spaces and publishing</li>
        </ul>
        <p className="text-sm text-ink-3">
          Your Wanderer account keeps everything it already has: browsing,
          reading, reacting and commenting stay exactly as they are.
        </p>
      </div>

      {entitled ? (
        <div className="card space-y-3">
          <h2 className="text-lg font-semibold">You're unlocked</h2>
          <p className="text-sm text-ink-2">
            Your account can create a character.
          </p>
          <button
            onClick={() => navigate('/characters/new')}
            className="px-4 py-2 rounded-lg text-sm font-semibold bg-gem text-gem-ink hover:bg-gem/90 transition-colors"
          >
            Create your character
          </button>
        </div>
      ) : (
        <div className="card space-y-3">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <Lock className="w-4 h-4 text-ink-3" />
            Not available yet
          </h2>
          <p className="text-sm text-ink-2">
            Writer Unlock isn't available during the closed beta.
          </p>
          {/* Names only what a Wanderer can actually do today — Follow is not
              functional yet, so it is not listed here. */}
          <p className="text-sm text-ink-2">
            Until then, your Wanderer account can continue browsing, reading
            stories, reacting and commenting exactly as it does today.
          </p>

          {/* Interest, not entitlement: one click, no email form, and the copy
              never implies the unlock is closer than it is. */}
          {onWaitlist ? (
            <div className="rounded-lg border border-gem/25 bg-gem-soft/40 p-3 space-y-2">
              <p className="flex items-center gap-2 text-sm font-semibold text-ink">
                <Check className="w-4 h-4 text-gem" />
                You're on the Writer waitlist.
              </p>
              {/* No notification system exists yet, so the copy must not
                  promise one — it points back here instead. */}
              <p className="text-sm text-ink-2">
                Your interest is recorded. There's no email notification yet, so
                check back here — your account is unchanged until the Writer
                Unlock is available.
              </p>
              <button
                onClick={handleLeave}
                disabled={busy}
                className="text-sm text-ink-3 hover:text-ink-2 underline underline-offset-2 transition-colors disabled:opacity-50"
              >
                {busy ? 'Removing…' : 'Remove me from the waitlist'}
              </button>
            </div>
          ) : (
            <div className="pt-1 space-y-3">
              {/* Only shown before joining: once on the list, an invitation to
                  join reads as a broken state. */}
              <p className="text-sm text-ink-3">
                Join the Writer waitlist if you'd like early access when Writer
                Unlock becomes available.
              </p>
              <div>
                <button
                  onClick={handleJoin}
                  disabled={busy}
                  className="px-4 py-2 rounded-lg text-sm font-semibold bg-gem text-gem-ink hover:bg-gem/90 transition-colors disabled:opacity-50"
                >
                  {busy ? 'Joining…' : 'Join the Writer waitlist'}
                </button>
                <p className="text-xs text-ink-3 mt-2">
                  One click — no email to fill in.
                </p>
              </div>
            </div>
          )}
          {waitlistError && (
            <p className="text-sm text-red-400">{waitlistError}</p>
          )}

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button
              onClick={() => navigate('/')}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-surface-elevated text-ink-2 hover:text-ink transition-colors"
            >
              Back to the Commons
            </button>
            <button
              onClick={() => navigate('/profile')}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-surface-elevated text-ink-2 hover:text-ink transition-colors"
            >
              My Account
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
