import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { StorySpaceRead, StorySpaceChannel, StorySpacePost } from '@/lib/types';
import ChannelList from '@/components/storyspace/ChannelList';
import PostList from '@/components/storyspace/PostList';
import PostInput from '@/components/storyspace/PostInput';

export default function StorySpaceDetail() {
  const { spaceId } = useParams<{ spaceId: string }>();

  const [space, setSpace] = useState<StorySpaceRead | null>(null);
  const [spaceLoading, setSpaceLoading] = useState(true);
  const [spaceError, setSpaceError] = useState('');

  const [activeChannel, setActiveChannel] = useState<StorySpaceChannel | null>(null);
  const [posts, setPosts] = useState<StorySpacePost[]>([]);
  const [postsLoading, setPostsLoading] = useState(false);

  const feedBottomRef = useRef<HTMLDivElement>(null);
  const feedRef = useRef<HTMLDivElement>(null);

  // Load space + default to first channel
  useEffect(() => {
    if (!spaceId) return;
    setSpaceLoading(true);
    setSpaceError('');
    apiClient
      .getStorySpace(Number(spaceId))
      .then((data) => {
        setSpace(data);
        if (data.channels.length > 0) {
          setActiveChannel(data.channels[0]);
        }
      })
      .catch((err: unknown) => {
        setSpaceError((err as Error).message || 'Could not load space.');
      })
      .finally(() => setSpaceLoading(false));
  }, [spaceId]);

  // Fetch posts whenever the active channel changes
  const loadPosts = useCallback(async (sid: number, ch: StorySpaceChannel) => {
    setPostsLoading(true);
    try {
      const data = await apiClient.getSpacePosts(sid, ch.id);
      setPosts(data);
    } catch {
      setPosts([]);
    } finally {
      setPostsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!spaceId || !activeChannel) return;
    void loadPosts(Number(spaceId), activeChannel);
  }, [spaceId, activeChannel, loadPosts]);

  // Scroll to bottom when new posts arrive
  useEffect(() => {
    feedBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [posts.length]);

  function handleSelectChannel(ch: StorySpaceChannel) {
    if (ch.id === activeChannel?.id) return;
    setPosts([]);
    setActiveChannel(ch);
  }

  async function handleSend(content: string) {
    if (!spaceId || !activeChannel) return;
    const post = await apiClient.createSpacePost(Number(spaceId), activeChannel.id, {
      content,
      content_type: activeChannel.channel_type === 'chat' ? 'ooc' : 'ic',
    });
    setPosts((prev) => [...prev, post]);
    // Ensure the feed scrolls to show the new post immediately
    setTimeout(() => feedBottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 50);
  }

  // ── Loading ──────────────────────────────────────────────────────────────────

  if (spaceLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="space-y-3 w-64">
          <div className="h-5 bg-gray-800 rounded animate-pulse w-48" />
          <div className="h-3 bg-gray-800 rounded animate-pulse w-64" />
        </div>
      </div>
    );
  }

  if (spaceError) {
    return (
      <div className="max-w-xl mx-auto px-6 py-10">
        <Link to="/spaces" className="text-sm text-gray-500 hover:text-gray-300 transition-colors mb-6 inline-block">
          ← Story Spaces
        </Link>
        <div className="rounded-xl bg-red-900/20 border border-red-700/40 px-4 py-3 text-sm text-red-400">
          {spaceError}
        </div>
      </div>
    );
  }

  // ── Full layout ──────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Top bar */}
      <div className="flex-shrink-0 flex items-center gap-3 px-4 py-2.5 border-b border-gray-800/80 bg-gray-950/60 backdrop-blur-sm min-h-0">
        <Link
          to="/spaces"
          className="text-gray-600 hover:text-gray-400 transition-colors p-1 rounded-lg hover:bg-gray-800"
          aria-label="Back to Story Spaces"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </Link>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-gray-100 truncate">{space?.name}</p>
          {activeChannel && (
            <p className="text-[11px] text-gray-600 leading-none mt-0.5 truncate">
              {activeChannel.name}
            </p>
          )}
        </div>
        <div className="flex-shrink-0 text-[10px] text-gray-700 flex items-center gap-1">
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
          </svg>
          {space?.member_count} {space?.member_count === 1 ? 'member' : 'members'}
        </div>
      </div>

      {/* Body: channel sidebar + post area */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Channel sidebar */}
        <aside className="w-44 flex-shrink-0 border-r border-gray-800/80 overflow-y-auto bg-gray-950">
          {space && (
            <ChannelList
              channels={space.channels}
              activeChannelId={activeChannel?.id ?? null}
              onSelect={handleSelectChannel}
            />
          )}
        </aside>

        {/* Post area */}
        <div className="flex flex-1 flex-col min-w-0 min-h-0">
          {/* Feed */}
          <div ref={feedRef} className="flex-1 overflow-y-auto min-h-0">
            <PostList posts={posts} loading={postsLoading} />
            <div ref={feedBottomRef} />
          </div>

          {/* Input */}
          {activeChannel && (
            <div className="flex-shrink-0">
              <PostInput
                onSend={handleSend}
                channelType={activeChannel.channel_type}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
