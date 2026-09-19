/**
 * The one sentence about the post-deletion character-creation cooldown, shown
 * inside both character-deletion dialogs (CharacterDetail and the draft
 * roster), so the two cannot drift apart.
 *
 * The server sets ``next_character_allowed_at`` on every delete UNLESS
 * ``is_seeder_account`` holds — and ``/users/me`` serialises that exact
 * predicate as ``is_seeder`` (``is_admin`` likewise covers ``ADMIN_EMAILS``),
 * so ``isFounder(user)`` here is a read of the server's own answer, not a
 * second copy of its policy.
 *
 * Three states, all truthful:
 *   - founder/seeder  → nothing. They are exempt; telling them to wait 24h
 *                        was the false claim Phase 5.3 removes.
 *   - ordinary account → the 24-hour wait, stated plainly.
 *   - account unknown  → the page could not load ``/users/me``; say the wait
 *                        may apply rather than guess either way.
 */
import type { User } from '@/lib/types';
import { isFounder } from '@/lib/entitlements';

export default function CharacterDeleteCooldownNote({ user }: { user: User | null | undefined }) {
  if (isFounder(user)) return null;
  if (!user) {
    return (
      <p className="text-amber-400">
        Unless your account is exempt, you will need to wait <strong>24 hours</strong> before
        creating a new character.
      </p>
    );
  }
  return (
    <p className="text-amber-400">
      After deleting, you must wait <strong>24 hours</strong> before creating a new character.
    </p>
  );
}
