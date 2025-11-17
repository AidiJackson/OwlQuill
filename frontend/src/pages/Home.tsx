import { useState, useEffect } from 'react';
import { apiClient } from '@/lib/apiClient';
import type { Post, Realm, Character } from '@/lib/types';

export default function Home() {
  const [realms, setRealms] = useState<Realm[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [showReportModal, setShowReportModal] = useState<number | null>(null);
  const [reportReason, setReportReason] = useState<'harassment' | 'nsfw' | 'spam' | 'other'>('spam');
  const [reportDetails, setReportDetails] = useState('');

  useEffect(() => {
    const loadData = async () => {
      try {
        // Load feed posts from realms the user is a member of
        const feedPosts = await apiClient.getFeed();
        setPosts(feedPosts);

        // Load realms and characters for display mapping
        const [realmsData, charactersData] = await Promise.all([
          apiClient.getRealms(),
          apiClient.getCharacters()
        ]);
        setRealms(realmsData);
        setCharacters(charactersData);
      } catch (error) {
        console.error('Failed to load data:', error);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, []);

  const getRealmName = (realmId?: number): string => {
    if (!realmId) return 'Unknown Realm';
    const realm = realms.find(r => r.id === realmId);
    return realm?.name || 'Unknown Realm';
  };

  const getCharacterName = (characterId?: number): string | null => {
    if (!characterId) return null;
    const character = characters.find(c => c.id === characterId);
    return character?.name || null;
  };

  const getPostTypeBadge = (contentType: string) => {
    const badges = {
      ic: { label: 'IC', className: 'bg-purple-600 text-white' },
      ooc: { label: 'OOC', className: 'bg-blue-600 text-white' },
      narration: { label: 'NARRATION', className: 'bg-amber-600 text-white' }
    };
    const badge = badges[contentType as keyof typeof badges] || badges.ic;
    return (
      <span className={`px-2 py-1 text-xs font-semibold rounded ${badge.className}`}>
        {badge.label}
      </span>
    );
  };

  const handleBlockUser = async (userId: number) => {
    if (confirm('Are you sure you want to block this user?')) {
      try {
        await apiClient.createBlock(userId);
        alert('User blocked successfully. Their content will no longer appear in your feed.');
        window.location.reload();
      } catch (error) {
        console.error('Failed to block user:', error);
        alert('Failed to block user. Please try again.');
      }
    }
  };

  const handleReportPost = async (postId: number) => {
    try {
      await apiClient.createReport({
        target_type: 'post',
        target_id: postId,
        reason: reportReason,
        details: reportDetails || undefined,
      });
      alert('Report submitted successfully. Thank you for helping keep the community safe.');
      setShowReportModal(null);
      setReportDetails('');
      setReportReason('spam');
    } catch (error) {
      console.error('Failed to report post:', error);
      alert('Failed to submit report. Please try again.');
    }
  };

  if (loading) {
    return (
      <div className="p-8">
        <p className="text-gray-400">Loading...</p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-8">
      <h1 className="text-3xl font-bold mb-8">Home Feed</h1>

      {posts.length === 0 ? (
        <div className="card text-center">
          <p className="text-gray-400 mb-4">No posts yet!</p>
          <p className="text-sm text-gray-500">
            Join a realm and start posting to see content here.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {posts.map((post) => {
            const characterName = getCharacterName(post.character_id);
            const realmName = getRealmName(post.realm_id);

            return (
              <div key={post.id} className="card">
                {/* Post header with metadata */}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    {getPostTypeBadge(post.content_type)}
                    <span className="text-sm text-gray-400">
                      {characterName && <span className="font-medium text-owl-400">{characterName}</span>}
                      {characterName && ' in '}
                      <span className="text-owl-300">{realmName}</span>
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-500">
                      {new Date(post.created_at).toLocaleDateString()}
                    </span>
                    <div className="relative group">
                      <button className="text-gray-400 hover:text-gray-200 px-2">⋮</button>
                      <div className="hidden group-hover:block absolute right-0 mt-2 w-48 bg-gray-800 border border-gray-700 rounded shadow-lg z-10">
                        <button
                          onClick={() => handleBlockUser(post.author_user_id)}
                          className="block w-full text-left px-4 py-2 text-sm hover:bg-gray-700"
                        >
                          Block User
                        </button>
                        <button
                          onClick={() => setShowReportModal(post.id)}
                          className="block w-full text-left px-4 py-2 text-sm hover:bg-gray-700"
                        >
                          Report Post
                        </button>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Post content */}
                {post.title && (
                  <h3 className="text-xl font-semibold mb-2">{post.title}</h3>
                )}
                <p className="text-gray-300 whitespace-pre-wrap">{post.content}</p>

                {/* Report modal */}
                {showReportModal === post.id && (
                  <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
                    <div className="bg-gray-800 p-6 rounded-lg max-w-md w-full mx-4">
                      <h3 className="text-xl font-bold mb-4">Report Post</h3>
                      <div className="space-y-4">
                        <div>
                          <label className="block text-sm font-medium mb-2">Reason</label>
                          <select
                            value={reportReason}
                            onChange={(e) => setReportReason(e.target.value as any)}
                            className="input"
                          >
                            <option value="harassment">Harassment</option>
                            <option value="nsfw">NSFW Content</option>
                            <option value="spam">Spam</option>
                            <option value="other">Other</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-sm font-medium mb-2">Additional Details (Optional)</label>
                          <textarea
                            value={reportDetails}
                            onChange={(e) => setReportDetails(e.target.value)}
                            className="textarea"
                            rows={3}
                            placeholder="Provide any additional context..."
                          />
                        </div>
                        <div className="flex gap-4">
                          <button
                            onClick={() => handleReportPost(post.id)}
                            className="btn btn-primary flex-1"
                          >
                            Submit Report
                          </button>
                          <button
                            onClick={() => setShowReportModal(null)}
                            className="btn btn-secondary flex-1"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
