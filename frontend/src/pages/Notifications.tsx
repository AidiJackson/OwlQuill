import { useState, useEffect } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { Heart, UserPlus, FileText, Filter } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { Notification } from '@/lib/types';

function getNotificationIcon(type: Notification['type']) {
  switch (type) {
    case 'reaction':
      return <Heart className="w-5 h-5 text-red-400" />;
    case 'connection':
      return <UserPlus className="w-5 h-5 text-owl-400" />;
    case 'scene_post':
      return <FileText className="w-5 h-5 text-blue-400" />;
    default:
      return <FileText className="w-5 h-5 text-gray-400" />;
  }
}

function getNotificationMessage(notification: Notification): string {
  switch (notification.type) {
    case 'reaction':
      return 'liked your post';
    case 'connection':
      return 'started following you';
    case 'scene_post':
      return 'posted in your realm';
    case 'realm_join':
      return 'joined your realm';
    default:
      return 'new activity';
  }
}

export default function Notifications() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [onlyUnread, setOnlyUnread] = useState(false);
  const [hasMore, setHasMore] = useState(true);

  const fetchNotifications = async (reset = false) => {
    setLoading(true);
    try {
      const skip = reset ? 0 : notifications.length;
      const newNotifs = await apiClient.getNotifications(onlyUnread, skip, 20);

      if (reset) {
        setNotifications(newNotifs);
      } else {
        setNotifications(prev => [...prev, ...newNotifs]);
      }

      setHasMore(newNotifs.length === 20);
    } catch (error) {
      console.error('Failed to fetch notifications:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchNotifications(true);
  }, [onlyUnread]);

  const handleMarkAllRead = async () => {
    const unreadIds = notifications.filter(n => !n.is_read).map(n => n.id);
    if (unreadIds.length === 0) return;

    try {
      await apiClient.markNotificationsRead(unreadIds);
      setNotifications(prev =>
        prev.map(n => ({ ...n, is_read: true }))
      );
    } catch (error) {
      console.error('Failed to mark notifications as read:', error);
    }
  };

  return (
    <div className="container mx-auto max-w-4xl p-6">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-3xl font-bold mb-4">Notifications</h1>

        <div className="flex items-center justify-between">
          {/* Filter */}
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-gray-400" />
            <button
              onClick={() => setOnlyUnread(!onlyUnread)}
              className={`px-3 py-1 rounded-lg text-sm transition-colors ${
                onlyUnread
                  ? 'bg-owl-500 text-white'
                  : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
              }`}
            >
              {onlyUnread ? 'Unread only' : 'All'}
            </button>
          </div>

          {/* Mark all read */}
          {notifications.some(n => !n.is_read) && (
            <button
              onClick={handleMarkAllRead}
              className="text-sm text-owl-400 hover:text-owl-300"
            >
              Mark all as read
            </button>
          )}
        </div>
      </div>

      {/* Notifications list */}
      {loading && notifications.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          Loading notifications...
        </div>
      ) : notifications.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-gray-400">
            {onlyUnread ? 'No unread notifications' : 'No notifications yet'}
          </p>
        </div>
      ) : (
        <>
          <div className="space-y-2">
            {notifications.map(notification => (
              <div
                key={notification.id}
                className={`p-4 rounded-lg border transition-colors ${
                  !notification.is_read
                    ? 'bg-gray-850 border-gray-700'
                    : 'bg-gray-900 border-gray-800'
                } hover:border-gray-700`}
              >
                <div className="flex items-start gap-4">
                  <div className="mt-1">
                    {getNotificationIcon(notification.type)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm">
                      <span className="font-medium">Someone</span>{' '}
                      <span className="text-gray-400">
                        {getNotificationMessage(notification)}
                      </span>
                    </p>
                    <p className="text-xs text-gray-500 mt-1">
                      {formatDistanceToNow(new Date(notification.created_at), {
                        addSuffix: true
                      })}
                    </p>
                  </div>
                  {!notification.is_read && (
                    <div className="w-2 h-2 bg-owl-500 rounded-full mt-2" />
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Load more */}
          {hasMore && (
            <div className="mt-6 text-center">
              <button
                onClick={() => fetchNotifications(false)}
                disabled={loading}
                className="px-6 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors disabled:opacity-50"
              >
                {loading ? 'Loading...' : 'Load more'}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
