import { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import { useAuthStore } from '@/lib/store';
import type { PublicUserProfile, ProfileTimelineItem, CharacterSearchResult } from '@/lib/types';
import {
  Camera,
  MapPin,
  Calendar,
  Feather,
  Heart,
  MessageCircle,
  Share2,
  BookOpen,
  UserPlus,
  Sparkles,
  RefreshCw,
} from 'lucide-react';
import AvatarPickerModal from '@/components/AvatarPickerModal';

type Tab = 'timeline' | 'characters' | 'stories' | 'media' | 'mentions';

export default function UserProfile() {
  const { username } = useParams<{ username: string }>();
  const navigate = useNavigate();
  const authUser = useAuthStore((s) => s.user);

  const [profile, setProfile] = useState<PublicUserProfile | null>(null);
  const [timeline, setTimeline] = useState<ProfileTimelineItem[]>([]);
  const [characters, setCharacters] = useState<CharacterSearchResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('timeline');

  const isOwnProfile = authUser?.username === username;
  const isAdmin = (() => {
    if (!authUser?.email) return false;
    const adminList = (import.meta.env.VITE_ADMIN_EMAILS || '').split(',').map((e: string) => e.trim().toLowerCase()).filter(Boolean);
    return adminList.includes(authUser.email.toLowerCase());
  })();

  const setUser = useAuthStore((s) => s.setUser);

  // Cover generation (admin-only beta)
  const [showCoverGen, setShowCoverGen] = useState(false);
  const [coverGenLoading, setCoverGenLoading] = useState(false);
  const [coverGenError, setCoverGenError] = useState('');

  // Avatar picker
  const [showAvatarPicker, setShowAvatarPicker] = useState(false);

  const coverPresets = [
    { id: 'enchanted_library', label: 'Enchanted Library' },
    { id: 'midnight_citadel', label: 'Midnight Citadel' },
    { id: 'celestial_garden', label: 'Celestial Garden' },
  ];

  const handleGenerateCover = async (presetName: string) => {
    setCoverGenLoading(true);
    setCoverGenError('');
    try {
      const result = await apiClient.generateProfileCover(presetName);
      setProfile((prev) => prev ? { ...prev, cover_url: result.cover_url } : prev);
      setShowCoverGen(false);
    } catch (err) {
      setCoverGenError(err instanceof Error ? err.message : 'Failed to generate cover.');
    } finally {
      setCoverGenLoading(false);
    }
  };

  useEffect(() => {
    if (!username) return;
    setLoading(true);
    setError(null);

    Promise.all([
      apiClient.getUserProfile(username),
      apiClient.getUserTimeline(username, 20),
      apiClient.getUserCharacters(username),
    ])
      .then(([profileData, timelineData, charsData]) => {
        setProfile(profileData);
        setTimeline(timelineData);
        setCharacters(charsData);
      })
      .catch(() => setError('User not found'))
      .finally(() => setLoading(false));
  }, [username]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-quill-500/30 border-t-quill-500 rounded-full animate-spin mx-auto mb-4" />
          <p className="text-[#E8ECEF]/60">Loading profile...</p>
        </div>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center">
        <p className="text-[#E8ECEF]/60 mb-4">{error || 'User not found'}</p>
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
    characters: characters.length,
    realms: 0,
    followers: 0,
  };

  const tabs: { id: Tab; label: string }[] = [
    { id: 'timeline', label: 'Timeline' },
    { id: 'characters', label: 'Characters' },
    { id: 'stories', label: 'Stories' },
    { id: 'media', label: 'Media' },
    { id: 'mentions', label: 'Mentions' },
  ];

  return (
    <div className="min-h-screen bg-[#0F1419]">
      {/* === HERO SECTION — cover fills behind the fixed nav === */}
      <div className="relative h-[380px] sm:h-[440px] md:h-[500px] w-full overflow-hidden bg-gradient-to-br from-quill-700 via-quill-600 to-quill-500">
        {/* Cover image (if set) */}
        {profile.cover_url && (
          <img
            src={profile.cover_url}
            alt="Profile cover"
            className="absolute inset-0 w-full h-full object-cover"
          />
        )}

        {/* Gradient Overlay */}
        <div className="absolute inset-0 bg-gradient-to-b from-[#1A1D23]/30 via-transparent to-[#1A1D23]/90" />

        {/* Subtle Pattern Overlay (only when no cover image) */}
        {!profile.cover_url && (
          <div
            className="absolute inset-0 opacity-[0.03]"
            style={{
              backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='1'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
            }}
          />
        )}

        {/* Hero Right: Avatar with Edit Cover above / Edit Profile below */}
        <div className="absolute right-4 sm:right-8 md:right-12 top-1/2 -translate-y-1/2 pt-[36px] z-20 flex flex-col items-center gap-3 sm:gap-4">
          {isOwnProfile && isAdmin && (
            <button
              onClick={() => setShowCoverGen((v) => !v)}
              className="bg-[#1A1D23]/60 backdrop-blur-md border border-[#E8ECEF]/10 text-white hover:bg-[#252930]/80 hover:border-[#E8ECEF]/20 px-3 sm:px-4 py-2 rounded-lg flex items-center gap-2 text-sm transition-all shadow-xl"
            >
              <Camera className="w-4 h-4" />
              <span className="hidden sm:inline">Edit Cover</span>
            </button>
          )}
          {isOwnProfile && !isAdmin && (
            <div className="bg-[#1A1D23]/60 backdrop-blur-md border border-[#E8ECEF]/10 px-3 sm:px-4 py-2 rounded-lg flex items-center gap-2 text-sm shadow-xl opacity-50 cursor-not-allowed">
              <Camera className="w-4 h-4 text-[#E8ECEF]/40" />
              <span className="hidden sm:inline text-[#E8ECEF]/40">Edit Cover</span>
              <span className="text-[10px] text-[#E8ECEF]/30 hidden sm:inline">— coming soon</span>
            </div>
          )}

          {/* Cover generation panel (admin-only beta) */}
          {showCoverGen && isAdmin && (
            <div className="bg-[#1A1D23]/90 backdrop-blur-md border border-[#E8ECEF]/10 rounded-lg p-3 shadow-xl space-y-2 min-w-[200px]">
              <p className="text-xs text-[#E8ECEF]/50 flex items-center gap-1">
                <Sparkles className="w-3 h-3" />
                Generate Cover (Beta)
              </p>
              {coverPresets.map((preset) => (
                <button
                  key={preset.id}
                  onClick={() => handleGenerateCover(preset.id)}
                  disabled={coverGenLoading}
                  className="w-full text-left text-sm text-[#E8ECEF]/80 hover:text-white hover:bg-[#2D3139]/60 px-2 py-1.5 rounded transition-colors disabled:opacity-40"
                >
                  {preset.label}
                </button>
              ))}
              {coverGenLoading && (
                <div className="flex items-center gap-2 text-xs text-[#E8ECEF]/50 px-2 py-1">
                  <RefreshCw className="w-3 h-3 animate-spin" />
                  Generating...
                </div>
              )}
              {coverGenError && (
                <p className="text-xs text-red-400 px-2">{coverGenError}</p>
              )}
            </div>
          )}

          {/* Avatar with premium frame */}
          <div className="relative">
            <div className="w-28 h-28 sm:w-36 sm:h-36 md:w-44 md:h-44 rounded-2xl bg-gradient-to-br from-quill-500 to-quill-700 p-1 sm:p-1.5 shadow-2xl shadow-quill-700/40">
              <div className="w-full h-full rounded-xl overflow-hidden ring-4 ring-[#1A1D23]/40 bg-[#2D3139]">
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
                  <div className="w-full h-full flex items-center justify-center text-3xl sm:text-4xl md:text-5xl font-bold text-white/80 bg-gradient-to-br from-quill-500 to-quill-700">
                    {profile.username.charAt(0).toUpperCase()}
                  </div>
                )}
              </div>
            </div>
            {isOwnProfile && (
              <button
                onClick={() => setShowAvatarPicker(true)}
                className="absolute -bottom-1 -right-1 sm:bottom-1 sm:right-1 w-8 h-8 sm:w-10 sm:h-10 rounded-xl bg-quill-500 hover:bg-quill-400 shadow-lg shadow-quill-500/30 flex items-center justify-center transition-all border border-white/10"
              >
                <Camera className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-white" />
              </button>
            )}
          </div>

          {isOwnProfile && (
            <button
              onClick={() => navigate('/profile')}
              className="bg-[#1A1D23]/60 backdrop-blur-md border border-[#E8ECEF]/10 text-white hover:bg-[#252930]/80 hover:border-[#E8ECEF]/20 px-3 sm:px-4 py-2 rounded-lg flex items-center gap-2 text-sm transition-all shadow-xl"
            >
              <span className="hidden sm:inline">Edit Profile</span>
              <span className="sm:hidden">Edit</span>
            </button>
          )}
        </div>

        {/* Profile Info Bar — anchored to bottom of cover */}
        <div className="absolute bottom-0 left-0 right-0 z-10">
          <div className="max-w-[1400px] mx-auto px-4 sm:px-8">
            <div className="pb-6 sm:pb-8">
              <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 sm:gap-8">
                {/* Left: Name, Stats, Tabs — right padding reserves space for the avatar group */}
                <div className="flex-1 min-w-0 pr-36 sm:pr-48 md:pr-56">
                  <div className="mb-3 sm:mb-4">
                    <h1 className="text-xl sm:text-2xl md:text-[32px] font-bold text-white tracking-tight truncate">
                      {displayName}
                    </h1>
                    <p className="text-[#E8ECEF]/60 text-sm sm:text-base md:text-lg mt-0.5">
                      @{profile.username}
                    </p>
                  </div>

                  {/* Stats Row */}
                  <div className="flex flex-wrap items-center gap-4 sm:gap-6 md:gap-8 mb-3 sm:mb-6">
                    {[
                      { label: 'Posts', value: stats.posts },
                      { label: 'Characters', value: stats.characters },
                      { label: 'Realms', value: stats.realms },
                      { label: 'Followers', value: stats.followers },
                    ].map((stat) => (
                      <button
                        key={stat.label}
                        className="flex items-baseline gap-1 sm:gap-2 hover:opacity-80 transition-opacity"
                      >
                        <span className="text-base sm:text-lg md:text-xl font-semibold text-white tracking-tight">
                          {stat.value.toLocaleString()}
                        </span>
                        <span className="text-[#E8ECEF]/60 text-xs sm:text-sm">
                          {stat.label}
                        </span>
                      </button>
                    ))}
                  </div>

                  {/* Tabs */}
                  <div className="flex items-center gap-1">
                    {tabs.map((tab) => (
                      <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        className={`px-3 sm:px-6 py-2 sm:py-2.5 rounded-lg text-xs sm:text-sm font-medium transition-all duration-200 ${
                          activeTab === tab.id
                            ? 'bg-quill-500 text-white shadow-lg shadow-quill-500/20'
                            : 'text-[#E8ECEF]/70 hover:text-white hover:bg-[#2D3139]/40'
                        }`}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Right: Action Buttons (non-own profile only) */}
                {!isOwnProfile && (
                  <div className="flex items-center gap-2 sm:gap-3 pb-0 sm:pb-2 flex-shrink-0">
                    <button className="bg-[#1A1D23]/60 backdrop-blur-md border border-[#E8ECEF]/10 text-white hover:bg-[#252930]/80 hover:border-[#E8ECEF]/20 px-3 sm:px-4 py-2 sm:py-2.5 rounded-lg flex items-center gap-2 text-sm transition-all shadow-lg">
                      <MessageCircle className="w-4 h-4" />
                      <span className="hidden sm:inline">Message</span>
                    </button>
                    <button className="bg-gradient-to-r from-quill-500 to-quill-400 text-white hover:from-quill-400 hover:to-quill-500 px-3 sm:px-4 py-2 sm:py-2.5 rounded-lg flex items-center gap-2 text-sm transition-all shadow-lg shadow-quill-500/30 border border-white/10">
                      <UserPlus className="w-4 h-4" />
                      Follow
                    </button>
                    <button className="bg-[#1A1D23]/60 backdrop-blur-md border border-[#E8ECEF]/10 text-white hover:bg-[#252930]/80 hover:border-[#E8ECEF]/20 p-2 sm:p-2.5 rounded-lg transition-all shadow-lg">
                      <Share2 className="w-4 h-4" />
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* === CONTENT AREA === */}
      <div className="bg-[#0F1419]">
        <div className="max-w-[1400px] mx-auto px-4 sm:px-8 py-8 sm:py-12">
          {/* Bio Section */}
          <div className="mb-8 max-w-3xl">
            {profile.bio && (
              <p className="text-[#E8ECEF]/90 text-base sm:text-lg leading-relaxed mb-6">
                {profile.bio}
              </p>
            )}

            {/* Writing Focus & Meta */}
            <div className="flex flex-col sm:flex-row sm:items-center gap-4 sm:gap-6">
              <div className="flex items-center gap-2 flex-wrap">
                {['Fantasy', 'Dark Academia', 'Romance'].map((focus, idx) => (
                  <span
                    key={idx}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-quill-500/20 text-quill-400 border border-quill-500/30 rounded-full text-xs hover:bg-quill-500/30 transition-all"
                  >
                    <Feather className="w-3 h-3" />
                    {focus}
                  </span>
                ))}
              </div>
              <div className="flex items-center gap-5 text-[#E8ECEF]/60">
                <span className="flex items-center gap-2 text-sm">
                  <MapPin className="w-4 h-4" />
                  Creative Realm
                </span>
                <span className="flex items-center gap-2 text-sm">
                  <Calendar className="w-4 h-4" />
                  Joined {joinDate}
                </span>
              </div>
            </div>
          </div>

          {/* Separator */}
          <div className="h-px bg-gradient-to-r from-transparent via-[#2D3139] to-transparent mb-8" />

          {/* Tab Content */}
          <div className="pb-12">
            {activeTab === 'timeline' && (
              <div className="space-y-6">
                {timeline.length === 0 ? (
                  <div className="rounded-2xl p-12 sm:p-16 text-center bg-[#1A1D23]/40 border border-[#2D3139]/60">
                    <Feather className="w-12 h-12 sm:w-14 sm:h-14 text-[#E8ECEF]/30 mx-auto mb-4 sm:mb-5" />
                    <h3 className="text-white text-xl font-semibold mb-2">
                      No Posts Yet
                    </h3>
                    <p className="text-[#E8ECEF]/60">
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

            {activeTab === 'characters' && (
              <div>
                {characters.length === 0 ? (
                  <div className="rounded-2xl p-12 sm:p-16 text-center bg-[#1A1D23]/40 border border-[#2D3139]/60">
                    <Feather className="w-12 h-12 sm:w-14 sm:h-14 text-[#E8ECEF]/30 mx-auto mb-4 sm:mb-5" />
                    <h3 className="text-white text-xl font-semibold mb-2">
                      No Public Characters Yet
                    </h3>
                    <p className="text-[#E8ECEF]/60">
                      {isOwnProfile
                        ? 'Create your first character to share with the community.'
                        : `When ${profile.username} shares characters, they'll appear here.`}
                    </p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {characters.map((ch) => (
                      <Link
                        key={ch.id}
                        to={`/characters/${ch.id}`}
                        className="rounded-2xl p-5 bg-[#1A1D23]/40 border border-[#2D3139]/60 hover:border-quill-500/40 hover:bg-[#1A1D23]/60 transition-all group"
                      >
                        <div className="flex items-start gap-4">
                          {ch.avatar_url ? (
                            <img
                              src={ch.avatar_url}
                              alt={ch.name}
                              className="w-14 h-14 rounded-xl object-cover border border-[#2D3139] flex-shrink-0 group-hover:border-quill-500/30 transition-colors"
                            />
                          ) : (
                            <div className="w-14 h-14 rounded-xl bg-[#2D3139] border border-[#3D4149] flex items-center justify-center flex-shrink-0">
                              <Feather className="w-6 h-6 text-[#E8ECEF]/30" />
                            </div>
                          )}
                          <div className="min-w-0 flex-1">
                            <h4 className="font-semibold text-white truncate group-hover:text-quill-400 transition-colors">
                              {ch.name}
                            </h4>
                            {ch.species && (
                              <p className="text-sm text-[#E8ECEF]/50 mt-0.5">{ch.species}</p>
                            )}
                            {ch.short_bio && (
                              <p className="text-sm text-[#E8ECEF]/60 mt-2 line-clamp-2 leading-relaxed">
                                {ch.short_bio}
                              </p>
                            )}
                          </div>
                        </div>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeTab === 'stories' && (
              <div className="rounded-2xl p-12 sm:p-16 text-center bg-[#1A1D23]/40 border border-[#2D3139]/60">
                <BookOpen className="w-12 h-12 sm:w-14 sm:h-14 text-[#E8ECEF]/30 mx-auto mb-4 sm:mb-5" />
                <h3 className="text-white text-xl font-semibold mb-2">
                  No Stories Yet
                </h3>
                <p className="text-[#E8ECEF]/60">
                  Your long-form stories and campaigns will appear here
                </p>
              </div>
            )}

            {activeTab === 'media' && (
              <div className="rounded-2xl p-12 sm:p-16 text-center bg-[#1A1D23]/40 border border-[#2D3139]/60">
                <Camera className="w-12 h-12 sm:w-14 sm:h-14 text-[#E8ECEF]/30 mx-auto mb-4 sm:mb-5" />
                <h3 className="text-white text-xl font-semibold mb-2">
                  No Media Yet
                </h3>
                <p className="text-[#E8ECEF]/60">
                  Images and moodboards you've shared will appear here
                </p>
              </div>
            )}

            {activeTab === 'mentions' && (
              <div className="rounded-2xl p-12 sm:p-16 text-center bg-[#1A1D23]/40 border border-[#2D3139]/60">
                <MessageCircle className="w-12 h-12 sm:w-14 sm:h-14 text-[#E8ECEF]/30 mx-auto mb-4 sm:mb-5" />
                <h3 className="text-white text-xl font-semibold mb-2">
                  No Mentions Yet
                </h3>
                <p className="text-[#E8ECEF]/60">
                  Posts where you've been mentioned will appear here
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      <AvatarPickerModal
        open={showAvatarPicker}
        onClose={() => setShowAvatarPicker(false)}
        onSaved={(avatarUrl) => {
          setProfile((prev) => prev ? { ...prev, avatar_url: avatarUrl } : prev);
          if (authUser) setUser({ ...authUser, avatar_url: avatarUrl });
          setShowAvatarPicker(false);
        }}
      />
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
