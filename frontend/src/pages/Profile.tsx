import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Lock, Check, RefreshCw, ChevronRight, Pencil } from 'lucide-react';
import { useAuthStore } from '@/lib/store';
import { apiClient } from '@/lib/apiClient';
import { canUseCreatorTools } from '@/lib/entitlements';

/** Curated default avatars — small inline SVG sigils, no upload required.
 *  For a Writer the sigil stays private (their public face is the character);
 *  for a Wanderer it is the avatar shown beside their public Wanderer
 *  username on comments. */
const AVATAR_PRESETS: { id: string; label: string; url: string }[] = [
  ['ember',    'Ember',    '#f59e0b', '#7c2d12', 'M32 14 L38 28 L52 32 L38 36 L32 50 L26 36 L12 32 L26 28 Z'],
  ['tide',     'Tide',     '#38bdf8', '#1e3a8a', 'M12 38 Q22 28 32 38 T52 38 Q42 48 32 42 T12 38 Z'],
  ['grove',    'Grove',    '#34d399', '#064e3b', 'M32 12 Q46 26 32 52 Q18 26 32 12 Z'],
  ['dusk',     'Dusk',     '#a78bfa', '#312e81', 'M40 14 A18 18 0 1 0 50 40 A14 14 0 1 1 40 14 Z'],
  ['rose',     'Rose',     '#fb7185', '#881337', 'M32 18 A8 8 0 0 1 46 24 Q46 38 32 46 Q18 38 18 24 A8 8 0 0 1 32 18 Z'],
  ['aurum',    'Aurum',    '#fbbf24', '#78350f', 'M32 12 L36 28 L52 32 L36 36 L32 52 L28 36 L12 32 L28 28 Z'],
  ['mist',     'Mist',     '#94a3b8', '#1e293b', 'M20 40 A12 12 0 1 1 30 22 A10 10 0 1 1 46 30 A8 8 0 1 1 44 40 Z'],
  ['sol',      'Sol',      '#f97316', '#7c2d12', 'M32 20 A12 12 0 1 0 32 44 A12 12 0 1 0 32 20 Z'],
].map(([id, label, from, to, glyph]) => ({
  id,
  label,
  url: `data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">` +
    `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">` +
    `<stop offset="0" stop-color="${from}"/><stop offset="1" stop-color="${to}"/>` +
    `</linearGradient></defs>` +
    `<rect width="64" height="64" fill="url(#g)"/>` +
    `<path d="${glyph}" fill="rgba(255,255,255,0.85)"/>` +
    `</svg>`
  )}`,
}));

export default function Profile() {
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const [saving, setSaving] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);
  const [error, setError] = useState('');

  // A Writer's public identity is their character, so their account username
  // stays read-only private infrastructure. A Wanderer's username IS their
  // public identity, so it's theirs to edit.
  const isWriter = canUseCreatorTools(user);

  const [usernameDraft, setUsernameDraft] = useState(user?.username ?? '');
  const [savingUsername, setSavingUsername] = useState(false);
  const [usernameError, setUsernameError] = useState('');
  const [usernameSaved, setUsernameSaved] = useState(false);

  // Keep the draft in step with the account when /me resolves or changes
  // elsewhere — but never stomp on what the user is currently typing.
  useEffect(() => {
    if (user && !savingUsername) {
      setUsernameDraft((draft) => (draft === '' ? user.username : draft));
    }
  }, [user, savingUsername]);

  const handleSaveUsername = async () => {
    const next = usernameDraft.trim();
    if (!user || savingUsername || next === user.username) return;
    setSavingUsername(true);
    setUsernameError('');
    setUsernameSaved(false);
    try {
      const updated = await apiClient.updateMyUsername(next);
      setUser(updated);
      setUsernameDraft(updated.username);
      setUsernameSaved(true);
      setTimeout(() => setUsernameSaved(false), 3000);
    } catch (err) {
      // Surface the server's own validation message — it is the authority on
      // what's allowed, and it explains *why* the name was refused.
      setUsernameError(
        err instanceof Error ? err.message : 'Could not update your username.'
      );
    } finally {
      setSavingUsername(false);
    }
  };

  const handlePickAvatar = async (url: string) => {
    if (saving) return;
    setSaving(true);
    setError('');
    try {
      const updated = await apiClient.updateMe({ avatar_url: url });
      setUser(updated);
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 2000);
    } catch {
      setError('Could not save your avatar. Try again.');
    } finally {
      setSaving(false);
    }
  };

  if (!user) {
    return <div className="p-8">Loading...</div>;
  }

  const joinDate = new Date(user.created_at).toLocaleDateString(undefined, {
    month: 'long',
    year: 'numeric',
  });

  return (
    <div className="max-w-2xl mx-auto p-6 sm:p-8">
      <div className="mb-6">
        <h1 className="font-serif text-4xl font-medium tracking-[-0.02em] text-ink">My Account</h1>
        <p className="flex items-center gap-1.5 text-sm text-ink-3 mt-1">
          <Lock className="w-3.5 h-3.5" />
          {isWriter
            ? 'Private — only you can see this page. Your public identity on Ficshon is your character.'
            : 'Private — only you can see this page. Publicly you appear as your Wanderer username.'}
        </p>
      </div>

      {/* Avatar */}
      <div className="card mb-6">
        <div className="flex items-center gap-5 mb-5">
          <div className="w-20 h-20 rounded-2xl overflow-hidden bg-surface-elevated border border-edge-md flex-shrink-0">
            {user.avatar_url ? (
              <img src={user.avatar_url} alt="Account avatar" className="w-full h-full object-cover" />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-2xl text-ink-3">
                {user.username.charAt(0).toUpperCase()}
              </div>
            )}
          </div>
          <div>
            <h2 className="text-lg font-semibold">Account sigil</h2>
            <p className="text-sm text-ink-3">
              {isWriter
                ? 'Pick a sigil for your account. Your public content is shown under your character.'
                : 'Pick a sigil. It appears beside your Wanderer username on comments.'}
              {saving && <RefreshCw className="inline w-3.5 h-3.5 ml-2 animate-spin text-ink-2" />}
              {savedFlash && <span className="text-gem ml-2 inline-flex items-center gap-1"><Check className="w-3.5 h-3.5" />Saved</span>}
            </p>
            {error && <p className="text-sm text-red-400 mt-1">{error}</p>}
          </div>
        </div>

        <div className="grid grid-cols-4 sm:grid-cols-8 gap-3">
          {AVATAR_PRESETS.map((preset) => {
            const selected = user.avatar_url === preset.url;
            return (
              <button
                key={preset.id}
                onClick={() => handlePickAvatar(preset.url)}
                disabled={saving}
                title={preset.label}
                className={`relative aspect-square rounded-xl overflow-hidden border-2 transition-all disabled:opacity-60 ${
                  selected
                    ? 'border-gem/50 shadow-lg shadow-[var(--accent-glow)]'
                    : 'border-transparent hover:border-edge-md'
                }`}
              >
                <img src={preset.url} alt={preset.label} className="w-full h-full object-cover" />
                {selected && (
                  <span className="absolute bottom-0.5 right-0.5 w-4 h-4 rounded-full bg-gem flex items-center justify-center">
                    <Check className="w-3 h-3 text-gem-ink" />
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Account details */}
      <div className="card mb-6 space-y-4">
        <h2 className="text-lg font-semibold">Account details</h2>

        <div>
          <p className="text-sm text-ink-3">
            {isWriter ? 'Account username (private)' : 'Wanderer username'}
          </p>
          {isWriter ? (
            // A Writer's public identity is their character; the account
            // username stays private infrastructure and is shown here only so
            // support can be asked about it.
            <p className="text-base">{user.username}</p>
          ) : (
            <>
              <p className="text-xs text-ink-3 mt-0.5 mb-2">
                This is how you appear publicly — on your comments and
                reactions.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                {/* Reads as an editable field, not a disabled one: page-surface
                    background, a full-strength border and a pencil sitting in
                    the field. The old elevated-grey fill made it look locked. */}
                <div className="relative">
                  <input
                    value={usernameDraft}
                    onChange={(e) => setUsernameDraft(e.target.value)}
                    disabled={savingUsername}
                    aria-label="Wanderer username"
                    className="w-full pl-3 pr-9 py-2 rounded-lg bg-surface border border-edge-md text-base text-ink hover:border-gem/40 focus:outline-none focus:border-gem focus:ring-1 focus:ring-gem/30 transition-colors disabled:opacity-60"
                  />
                  <Pencil
                    className="w-3.5 h-3.5 text-ink-3 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none"
                    aria-hidden="true"
                  />
                </div>
                <button
                  onClick={handleSaveUsername}
                  disabled={savingUsername || usernameDraft.trim() === user.username}
                  className="px-4 py-2 rounded-lg text-sm font-semibold bg-gem text-gem-ink hover:bg-gem/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {savingUsername ? 'Saving…' : 'Save'}
                </button>
                {usernameDraft.trim() !== user.username && !savingUsername && (
                  <button
                    onClick={() => {
                      setUsernameDraft(user.username);
                      setUsernameError('');
                    }}
                    className="text-sm text-ink-3 hover:text-ink-2 transition-colors"
                  >
                    Cancel
                  </button>
                )}
              </div>
              {usernameError && (
                <p className="text-sm text-red-400 mt-2">{usernameError}</p>
              )}
              {usernameSaved && (
                <p className="text-sm text-gem mt-2 inline-flex items-center gap-1">
                  <Check className="w-3.5 h-3.5" />
                  Username updated
                </p>
              )}
              <p className="text-xs text-ink-3 mt-2">
                3–24 characters: letters, numbers, and single . _ - between
                them. You can change it again 14 days after a change.
              </p>
            </>
          )}
        </div>

        <div>
          <p className="text-sm text-ink-3">Email (private)</p>
          <p className="text-base">{user.email}</p>
        </div>
        <div>
          <p className="text-sm text-ink-3">Member since</p>
          <p className="text-base">{joinDate}</p>
        </div>
      </div>

      {/* Upgrade entry — restrained, and never a shortcut into character
          creation: it leads to the Writer Unlock gate, which is the only place
          the entitlement can be obtained.

          The whole card is the control, so it is a real <button>: click,
          Enter/Space and the focus ring all come from the element rather than
          being reimplemented on a div. The former "Learn more" button is gone
          rather than nested inside it — a button inside a button is invalid
          markup — and survives as the chevron affordance on the right. */}
      {!isWriter && (
        <button
          type="button"
          onClick={() => navigate('/become-a-writer')}
          className="card mb-6 w-full text-left flex flex-wrap items-center justify-between gap-3 hover:border-gem/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-gem/50 transition-colors"
        >
          <div>
            <h2 className="text-lg font-semibold">Become a Writer</h2>
            <p className="text-sm text-ink-2">
              Unlock one character and Ficshon's creator tools.
            </p>
          </div>
          <span className="flex items-center gap-1 text-sm font-semibold text-ink-2 flex-shrink-0">
            Learn more
            <ChevronRight className="w-4 h-4" />
          </span>
        </button>
      )}

      {/* Security */}
      <div className="card space-y-3">
        <h2 className="text-lg font-semibold">Security</h2>
        <p className="text-sm text-ink-2">
          To change your password, sign out and use “Forgot password” on the
          login screen — a reset link will be emailed to you.
        </p>
      </div>
    </div>
  );
}
