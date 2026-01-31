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
      <div className="relative h-80 sm:h-96 w-full overflow-hidden bg-gradient-to-br from-owl-600/30 via-owl-900/40 to-gray-900">
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-gray-950/90" />
        {isOwnProfile && (
          <button className="absolute bottom-4 right-4 glass-strong border border-white/20 text-white hover:bg-white/20 px-4 py-2 rounded-lg flex items-center gap-2 text-sm transition-colors">
            <Camera className="w-4 h-4" />
            Edit Cover
          </button>
        )}
      </div>

      <div className="max-w-4xl mx-auto px-6">
        <div className="relative -mt-20 mb-6">
          <div className="flex justify-end mb-2">
            <div className="relative">
              <div className="w-36 h-36 sm:w-40 sm:h-40 rounded-full ring-4 ring-gray-950 shadow-2xl overflow-hidden bg-gray-800">
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
                  <div className="w-full h-full flex items-center justify-center text-5xl font-bold text-gray-500 bg-gradient-to-br from-owl-500 to-owl-700">
                    {profile.username.charAt(0).toUpperCase()}
                  </div>
                )}
              </div>
              {isOwnProfile && (
                <button className="absolute bottom-2 right-2 w-11 h-11 rounded-full bg-owl-600 hover:bg-owl-700 shadow-lg flex items-center justify-center transition-colors">
                  <Camera className="w-5 h-5 text-white" />
                </button>
              )}
            </div>
          </div>

          <div className="glass-strong rounded-2xl p-8">
            <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-6 mb-6">
              <div className="flex-1">
                <h1 className="text-3xl sm:text-4xl font-bold text-white mb-2">
                  {displayName}
                </h1>
                <p className="text-white/60 mb-4">@{profile.username}</p>

                {profile.bio && (
                  <p className="text-white/90 mb-5 max-w-2xl leading-relaxed whitespace-pre-wrap">
                    {profile.bio}
                  </p>
                )}

                <div className="flex flex-wrap gap-2 mb-5">
                  {['Fantasy', 'Dark Academia', 'Romance'].map((focus, idx) => (
                    <span
                      key={idx}
                      className="inline-flex items-center gap-1 px-3 py-1.5 bg-owl-600/20 text-owl-400 border border-owl-500/30 rounded-full text-sm hover:bg-owl-600/30 transition-colors"
                    >
                      <Feather className="w-3 h-3" />
                      {focus}
                    </span>
                  ))}
                </div>

                <div className="flex items-center gap-6 text-sm text-white/60">
                  <div className="flex items-center gap-2">
                    <MapPin className="w-4 h-4" />
                    <span>Creative Realm</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Calendar className="w-4 h-4" />
                    <span>Joined {joinDate}</span>
                  </div>
                </div>
              </div>

              <div className="flex gap-3 flex-shrink-0">
                {isOwnProfile ? (
                  <button
                    onClick={() => navigate('/profile')}
                    className="btn btn-secondary flex items-center gap-2"
                  >
                    Edit Profile
                  </button>
                ) : (
                  <>
                    <button className="btn btn-secondary flex items-center gap-2">
                      <MessageCircle className="w-4 h-4" />
                      Message
                    </button>
                    <button className="btn btn-primary flex items-center gap-2 glow-hover">
                      <Heart className="w-4 h-4" />
                      Follow
                    </button>
                    <button className="btn btn-secondary p-2.5">
                      <Share2 className="w-4 h-4" />
                    </button>
                  </>
                )}
              </div>
            </div>

            <div className="flex items-center gap-8 pt-6 border-t border-white/10">
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
                  <div className="text-xl font-semibold text-white mb-1">
                    {stat.value.toLocaleString()}
                  </div>
                  <div className="text-white/60 text-sm">{stat.label}</div>
                </button>
              ))}
            </div>

            <div className="mt-6 glass rounded-xl p-1">
              <div className="flex gap-1">
                {tabs.map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`flex-1 py-2.5 px-4 rounded-lg text-sm font-medium transition-colors ${
                      activeTab === tab.id
                        ? 'bg-owl-600 text-white'
                        : 'text-white/60 hover:text-white hover:bg-white/10'
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
