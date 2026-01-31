import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import { useAuthStore } from '@/lib/store';
import type { PublicUserProfile } from '@/lib/types';

type Tab = 'timeline' | 'about';

export default function UserProfile() {
  const { username } = useParams<{ username: string }>();
  const navigate = useNavigate();
  const authUser = useAuthStore((s) => s.user);

  const [profile, setProfile] = useState<PublicUserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('timeline');

  // Composer state (UI only, no submit wired yet)
  const [composeContent, setComposeContent] = useState('');
  const [composeType, setComposeType] = useState<'ooc' | 'ic' | 'narration'>('ooc');
  const [composeKind, setComposeKind] = useState<'general' | 'open_starter' | 'finished_piece'>('general');

  const isOwnProfile = authUser?.username === username;

  useEffect(() => {
    if (!username) return;
    setLoading(true);
    setError(null);
    apiClient
      .getUserProfile(username)
      .then(setProfile)
      .catch(() => setError('User not found'))
      .finally(() => setLoading(false));
  }, [username]);

  if (loading) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center">
        <p className="text-gray-400">Loading profile...</p>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center">
        <p className="text-gray-400 mb-4">{error || 'User not found'}</p>
        <button onClick={() => navigate('/')} className="btn btn-secondary">
          Go Home
        </button>
      </div>
    );
  }

  const displayName = profile.display_name || profile.username;
  const joinDate = new Date(profile.created_at).toLocaleDateString('en-US', {
    month: 'long',
    year: 'numeric',
  });

  return (
    <div className="max-w-2xl mx-auto pb-8">
      {/* ── Cover Banner ── */}
      <div className="h-40 sm:h-52 bg-gradient-to-br from-owl-700 via-owl-900 to-gray-900 relative">
        {/* Subtle overlay pattern */}
        <div className="absolute inset-0 bg-gradient-to-t from-gray-950/60 to-transparent" />
      </div>

      {/* ── Avatar + Identity ── */}
      <div className="px-4 sm:px-6 -mt-16 relative z-10">
        <div className="flex items-end gap-4">
          {/* Avatar with frame */}
          <div className="w-28 h-28 sm:w-32 sm:h-32 rounded-full border-4 border-gray-950 bg-gray-800 overflow-hidden flex-shrink-0 ring-2 ring-owl-600/40">
            {profile.avatar_url ? (
              <img
                src={profile.avatar_url}
                alt={`${displayName}'s avatar`}
                className="w-full h-full object-cover"
                onError={(e) => {
                  e.currentTarget.style.display = 'none';
                  (e.currentTarget.nextSibling as HTMLElement | null)?.classList.remove('hidden');
                }}
              />
            ) : null}
            <div
              className={`w-full h-full flex items-center justify-center text-4xl font-bold text-gray-500 ${
                profile.avatar_url ? 'hidden' : ''
              }`}
            >
              {profile.username.charAt(0).toUpperCase()}
            </div>
          </div>

          {/* Name + username */}
          <div className="pb-2 min-w-0">
            <h1 className="text-2xl sm:text-3xl font-bold leading-tight truncate">
              {displayName}
            </h1>
            <p className="text-gray-400 text-sm sm:text-base">@{profile.username}</p>
          </div>
        </div>

        {/* Bio */}
        {profile.bio && (
          <p className="mt-4 text-gray-300 whitespace-pre-wrap text-sm sm:text-base leading-relaxed">
            {profile.bio}
          </p>
        )}

        {/* Join date */}
        <p className="mt-2 text-xs sm:text-sm text-gray-500">Joined {joinDate}</p>

        {/* Action buttons */}
        <div className="mt-4 flex gap-3">
          {isOwnProfile ? (
            <button
              onClick={() => navigate('/profile')}
              className="btn btn-secondary text-sm"
            >
              Edit Profile
            </button>
          ) : (
            <button className="btn btn-primary text-sm" disabled>
              Follow
            </button>
          )}
        </div>
      </div>

      {/* ── Stats Row ── */}
      <div className="px-4 sm:px-6 mt-6">
        <div className="flex gap-6 text-sm border-b border-gray-800 pb-4">
          {[
            { label: 'Posts', value: 0 },
            { label: 'Characters', value: 0 },
            { label: 'Realms', value: 0 },
            { label: 'Followers', value: 0 },
          ].map((stat) => (
            <span key={stat.label} className="text-gray-400">
              <span className="font-semibold text-gray-100">{stat.value}</span>{' '}
              {stat.label}
            </span>
          ))}
        </div>
      </div>

      {/* ── Tabs ── */}
      <div className="px-4 sm:px-6 mt-2">
        <div className="flex gap-1">
          {(['timeline', 'about'] as Tab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2.5 text-sm font-medium rounded-t-lg transition-colors ${
                activeTab === tab
                  ? 'text-owl-400 border-b-2 border-owl-500 bg-gray-900/50'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50'
              }`}
            >
              {tab === 'timeline' ? 'Timeline' : 'About'}
            </button>
          ))}
        </div>
      </div>

      {/* ── Tab Content ── */}
      <div className="px-4 sm:px-6 mt-4">
        {activeTab === 'timeline' && (
          <div>
            {/* Composer (own profile only, UI shell — no submit wired) */}
            {isOwnProfile && (
              <div className="card mb-6">
                <textarea
                  value={composeContent}
                  onChange={(e) => setComposeContent(e.target.value)}
                  className="textarea w-full mb-3"
                  placeholder="Share a thought, intro, or plot idea..."
                  rows={3}
                />
                <div className="flex flex-wrap items-center gap-3">
                  <select
                    value={composeType}
                    onChange={(e) =>
                      setComposeType(e.target.value as 'ooc' | 'ic' | 'narration')
                    }
                    className="input w-auto text-sm"
                  >
                    <option value="ooc">OOC</option>
                    <option value="ic">IC</option>
                    <option value="narration">Narration</option>
                  </select>
                  <select
                    value={composeKind}
                    onChange={(e) =>
                      setComposeKind(
                        e.target.value as 'general' | 'open_starter' | 'finished_piece'
                      )
                    }
                    className="input w-auto text-sm"
                  >
                    <option value="general">General</option>
                    <option value="open_starter">Open Starter</option>
                    <option value="finished_piece">Finished Piece</option>
                  </select>
                  <button
                    disabled={!composeContent.trim()}
                    className="btn btn-primary text-sm ml-auto"
                  >
                    Post
                  </button>
                </div>
              </div>
            )}

            {/* Timeline empty state (no fetch wired yet) */}
            <div className="card text-center py-10">
              <p className="text-gray-400 mb-1">No posts on this timeline yet.</p>
              <p className="text-sm text-gray-500">
                {isOwnProfile
                  ? 'Write something above to get started.'
                  : `When ${profile.username} posts, it will appear here.`}
              </p>
            </div>
          </div>
        )}

        {activeTab === 'about' && (
          <div className="card">
            <h3 className="text-lg font-semibold mb-4">About</h3>

            <div className="space-y-4">
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Bio</p>
                <p className="text-gray-300 whitespace-pre-wrap text-sm leading-relaxed">
                  {profile.bio || 'No bio yet.'}
                </p>
              </div>

              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">
                  Member Since
                </p>
                <p className="text-gray-300 text-sm">{joinDate}</p>
              </div>

              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">
                  Username
                </p>
                <p className="text-gray-300 text-sm">@{profile.username}</p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
