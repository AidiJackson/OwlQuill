import { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import { useAuthStore } from '@/lib/store';
import type { PublicUserProfile, ProfileTimelineItem } from '@/lib/types';
import {
  Camera,
  MapPin,
  Calendar,
  Feather,
  Heart,
  MessageCircle,
  Share2,
  BookOpen,
} from 'lucide-react';

type Tab = 'timeline' | 'stories' | 'media' | 'mentions';

export default function UserProfile() {
  const { username } = useParams<{ username: string }>();
  const navigate = useNavigate();
  const authUser = useAuthStore((s) => s.user);

  const [profile, setProfile] = useState<PublicUserProfile | null>(null);
  const [timeline, setTimeline] = useState<ProfileTimelineItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('timeline');

  const isOwnProfile = authUser?.username === username;

  useEffect(() => {
    if (!username) return;
    setLoading(true);
    setError(null);

    Promise.all([
      apiClient.getUserProfile(username),
      apiClient.getUserTimeline(username, 20),
    ])
      .then(([profileData, timelineData]) => {
        setProfile(profileData);
        setTimeline(timelineData);
      })
      .catch(() => setError('User not found'))
      .finally(() => setLoading(false));
  }, [username]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-owl-500/30 border-t-owl-500 rounded-full animate-spin mx-auto mb-4" />
          <p className="text-gray-400">Loading profile...</p>
        </div>
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

  const stats = {
    posts: timeline.filter((i) => i.type === 'post').length,
    characters: 0,
    realms: 0,
    followers: 0,
  };

  const tabs: { id: Tab; label: string }[] = [
    { id: 'timeline', label: 'Timeline' },
    { id: 'stories', label: 'Stories' },
    { id: 'media', label: 'Media' },
    { id: 'mentions', label: 'Mentions' },
  ];

  return (
    <div className="min-h-screen">
      {/* ── Cover Banner ── */}
      <div className="relative h-72 sm:h-80 md:h-96 w-full overflow-hidden bg-gradient-to-br from-owl-600/30 via-owl-900/40 to-gray-900">
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-gray-950/95" />

        {/* Avatar — right-aligned in cover zone */}
        <div className="absolute bottom-0 right-6 sm:right-10 translate-y-1/3 z-20">
          <div className="relative">
            <div className="w-40 h-40 sm:w-44 sm:h-44 md:w-48 md:h-48 rounded-full ring-[5px] ring-gray-950 shadow-[0_0_40px_rgba(139,92,246,0.25)] overflow-hidden bg-gray-800">
              <div className="absolute inset-[5px] rounded-full ring-2 ring-owl-500/40 z-10 pointer-events-none" />
              {profile.avatar_url ? (
                <img
                  src={profile.avatar_url}
                  alt={`${displayName}'s avatar`}
                  className="w-full h-full object-cover"
                  onError={(e) => {
                    e.currentTarget.style.display = 'none';
                  }}
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-5xl font-bold text-white/80 bg-gradient-to-br from-owl-500 to-owl-700">
                  {profile.username.charAt(0).toUpperCase()}
                </div>
              )}
            </div>
            {isOwnProfile && (
              <button className="absolute bottom-3 right-3 w-10 h-10 rounded-full bg-owl-600 hover:bg-owl-500 shadow-lg shadow-owl-600/30 flex items-center justify-center transition-colors z-20 ring-2 ring-gray-950">
                <Camera className="w-4 h-4 text-white" />
              </button>
            )}
          </div>
        </div>

        {/* Edit Cover — top-right so it doesn't clash with avatar */}
        {isOwnProfile && (
          <button className="absolute top-4 right-4 glass border border-white/20 text-white/80 hover:text-white hover:bg-white/20 px-3 py-1.5 rounded-lg flex items-center gap-2 text-xs transition-colors z-20">
            <Camera className="w-3.5 h-3.5" />
            Edit Cover
          </button>
        )}
      </div>

      {/* ── Unified Profile Bar ── */}
      <div className="max-w-4xl mx-auto px-4 sm:px-6">
        <div className="relative -mt-6 mb-6">
          <div className="glass-strong rounded-2xl border border-white/[0.06] overflow-hidden">
            {/* Top section: identity + actions */}
            <div className="px-6 sm:px-8 pt-6 sm:pt-8 pb-5">
              <div className="flex flex-col sm:flex-row sm:items-start gap-4">
                {/* Left: name, handle, bio, tags, meta */}
                <div className="flex-1 min-w-0 pr-0 sm:pr-48 md:pr-56">
                  <h1 className="text-2xl sm:text-3xl font-bold text-white truncate">
                    {displayName}
                  </h1>
                  <p className="text-white/50 text-sm mt-0.5">@{profile.username}</p>

                  {profile.bio && (
                    <p className="text-white/80 text-sm leading-relaxed mt-3 whitespace-pre-wrap line-clamp-3">
                      {profile.bio}
                    </p>
                  )}

                  <div className="flex flex-wrap gap-1.5 mt-3">
                    {['Fantasy', 'Dark Academia', 'Romance'].map((focus, idx) => (
                      <span
                        key={idx}
                        className="inline-flex items-center gap-1 px-2.5 py-1 bg-owl-600/15 text-owl-400 border border-owl-500/20 rounded-full text-xs"
                      >
                        <Feather className="w-3 h-3" />
                        {focus}
                      </span>
                    ))}
                  </div>

                  <div className="flex items-center gap-5 mt-3 text-xs text-white/50">
                    <span className="flex items-center gap-1.5">
                      <MapPin className="w-3.5 h-3.5" />
                      Creative Realm
                    </span>
                    <span className="flex items-center gap-1.5">
                      <Calendar className="w-3.5 h-3.5" />
                      Joined {joinDate}
                    </span>
                  </div>
                </div>

                {/* Right: action buttons */}
                <div className="flex gap-2 flex-shrink-0 sm:mt-1">
                  {isOwnProfile ? (
                    <button
                      onClick={() => navigate('/profile')}
                      className="btn btn-secondary text-sm flex items-center gap-2"
                    >
                      Edit Profile
                    </button>
                  ) : (
                    <>
                      <button className="btn btn-secondary text-sm flex items-center gap-1.5">
                        <MessageCircle className="w-4 h-4" />
                        Message
                      </button>
                      <button className="btn btn-primary text-sm flex items-center gap-1.5 glow-hover">
                        <Heart className="w-4 h-4" />
                        Follow
                      </button>
                      <button className="btn btn-secondary p-2">
                        <Share2 className="w-4 h-4" />
                      </button>
                    </>
                  )}
                </div>
              </div>
            </div>

            {/* Stats row */}
            <div className="px-6 sm:px-8 py-3 border-t border-white/[0.06] flex items-center gap-8">
              {[
                { label: 'Posts', value: stats.posts },
                { label: 'Characters', value: stats.characters },
                { label: 'Realms', value: stats.realms },
                { label: 'Followers', value: stats.followers },
              ].map((stat) => (
                <button
                  key={stat.label}
                  className="text-center hover:opacity-80 transition-opacity"
                >
                  <span className="text-lg font-semibold text-white">
                    {stat.value.toLocaleString()}
                  </span>
                  <span className="text-white/50 text-sm ml-1.5">{stat.label}</span>
                </button>
              ))}
            </div>

            {/* Tabs */}
            <div className="px-6 sm:px-8 py-2 border-t border-white/[0.06]">
              <div className="flex gap-1">
                {tabs.map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`py-2 px-4 rounded-lg text-sm font-medium transition-colors ${
                      activeTab === tab.id
                        ? 'bg-owl-600 text-white shadow-sm shadow-owl-600/20'
                        : 'text-white/50 hover:text-white hover:bg-white/10'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="pb-12 mt-6">
            {activeTab === 'timeline' && (
              <div className="space-y-6">
                {timeline.length === 0 ? (
                  <div className="glass-strong rounded-2xl p-12 text-center">
                    <Feather className="w-12 h-12 text-white/40 mx-auto mb-4" />
                    <h3 className="text-xl font-semibold text-white mb-2">
                      No Posts Yet
                    </h3>
                    <p className="text-white/60">
                      {isOwnProfile
                        ? 'Share your first post to get started.'
                        : `When ${profile.username} posts, it will appear here.`}
                    </p>
                  </div>
                ) : (
                  timeline.map((item, idx) => (
                    <TimelineItemCard
                      key={idx}
                      item={item}
                      profile={profile}
                    />
                  ))
                )}
              </div>
            )}

            {activeTab === 'stories' && (
              <div className="glass-strong rounded-2xl p-12 text-center">
                <BookOpen className="w-12 h-12 text-white/40 mx-auto mb-4" />
                <h3 className="text-xl font-semibold text-white mb-2">
                  No Stories Yet
                </h3>
                <p className="text-white/60">
                  Your long-form stories and campaigns will appear here
                </p>
              </div>
            )}

            {activeTab === 'media' && (
              <div className="glass-strong rounded-2xl p-12 text-center">
                <Camera className="w-12 h-12 text-white/40 mx-auto mb-4" />
                <h3 className="text-xl font-semibold text-white mb-2">
                  No Media Yet
                </h3>
                <p className="text-white/60">
                  Images and moodboards you've shared will appear here
                </p>
              </div>
            )}

            {activeTab === 'mentions' && (
              <div className="glass-strong rounded-2xl p-12 text-center">
                <MessageCircle className="w-12 h-12 text-white/40 mx-auto mb-4" />
                <h3 className="text-xl font-semibold text-white mb-2">
                  No Mentions Yet
                </h3>
                <p className="text-white/60">
                  Posts where you've been mentioned will appear here
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function TimelineItemCard({
  item,
  profile,
}: {
  item: ProfileTimelineItem;
  profile: PublicUserProfile;
}) {
  const displayName = profile.display_name || profile.username;
  const payload = item.payload as Record<string, unknown>;

  if (item.type === 'scene') {
    const scene = payload as {
      id?: number;
      title?: string;
      description?: string;
    };
    return (
      <Link
        to={`/scenes/${scene.id}`}
        className="block glass-strong rounded-2xl p-6 hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-gray-800 overflow-hidden flex-shrink-0">
            {profile.avatar_url ? (
              <img
                src={profile.avatar_url}
                alt={displayName}
                className="w-full h-full object-cover"
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-sm font-medium text-gray-400">
                {profile.username.charAt(0).toUpperCase()}
              </div>
            )}
          </div>
          <div>
            <p className="font-medium text-white">{displayName}</p>
            <p className="text-sm text-white/50">started a new scene</p>
          </div>
          {item.realm_name && (
            <span className="ml-auto text-sm text-owl-400 bg-owl-600/20 px-3 py-1 rounded-full">
              {item.realm_name}
            </span>
          )}
        </div>
        <div className="bg-gray-800/50 rounded-xl p-4 border border-white/10">
          <h4 className="font-semibold text-white mb-1">
            {scene.title || 'Untitled Scene'}
          </h4>
          {scene.description && (
            <p className="text-sm text-white/70 line-clamp-2">
              {scene.description}
            </p>
          )}
        </div>
      </Link>
    );
  }

  const post = payload as {
    id?: number;
    content?: string;
    title?: string;
    content_type?: string;
  };

  return (
    <div className="glass-strong rounded-2xl p-6">
      <div className="flex items-center gap-3 mb-4">
        <div className="w-10 h-10 rounded-full bg-gray-800 overflow-hidden flex-shrink-0">
          {profile.avatar_url ? (
            <img
              src={profile.avatar_url}
              alt={displayName}
              className="w-full h-full object-cover"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-sm font-medium text-gray-400">
              {profile.username.charAt(0).toUpperCase()}
            </div>
          )}
        </div>
        <div>
          <p className="font-medium text-white">{displayName}</p>
          <p className="text-sm text-white/50">
            {new Date(item.created_at).toLocaleDateString('en-US', {
              month: 'short',
              day: 'numeric',
            })}
          </p>
        </div>
        {item.realm_name && (
          <span className="ml-auto text-sm text-owl-400 bg-owl-600/20 px-3 py-1 rounded-full">
            {item.realm_name}
          </span>
        )}
      </div>

      {post.title && (
        <h4 className="font-semibold text-white mb-2">{post.title}</h4>
      )}

      <p className="text-white/90 whitespace-pre-wrap leading-relaxed">
        {post.content}
      </p>

      <div className="flex items-center gap-6 mt-4 pt-4 border-t border-white/10">
        <button className="flex items-center gap-2 text-white/50 hover:text-owl-400 transition-colors">
          <Heart className="w-4 h-4" />
          <span className="text-sm">0</span>
        </button>
        <button className="flex items-center gap-2 text-white/50 hover:text-owl-400 transition-colors">
          <MessageCircle className="w-4 h-4" />
          <span className="text-sm">0</span>
        </button>
        <button className="flex items-center gap-2 text-white/50 hover:text-owl-400 transition-colors ml-auto">
          <Share2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
