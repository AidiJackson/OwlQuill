import { useState } from 'react';
import { Lock, Check, RefreshCw } from 'lucide-react';
import { useAuthStore } from '@/lib/store';
import { apiClient } from '@/lib/apiClient';

/** Curated default avatars — small inline SVG sigils, no upload required.
 *  Accounts are private infrastructure; the avatar only ever appears in the
 *  owner's own UI (sidebar/account page), never on a public surface. */
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
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const [saving, setSaving] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);
  const [error, setError] = useState('');

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
          Private — only you can see this page. Your public identity on Ficshon is a character.
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
            <h2 className="text-lg font-semibold">Account avatar</h2>
            <p className="text-sm text-ink-3">
              Pick a sigil for your account.
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
          <p className="text-sm text-ink-3">Username</p>
          <p className="text-base">{user.username}</p>
        </div>
        <div>
          <p className="text-sm text-ink-3">Email</p>
          <p className="text-base">{user.email}</p>
        </div>
        <div>
          <p className="text-sm text-ink-3">Member since</p>
          <p className="text-base">{joinDate}</p>
        </div>
      </div>

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
