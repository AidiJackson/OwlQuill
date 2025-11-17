import { Link } from 'react-router-dom';
import { formatDistanceToNow } from 'date-fns';
import { X, Heart, UserPlus, FileText } from 'lucide-react';
import type { Notification } from '@/lib/types';

interface NotificationPanelProps {
  notifications: Notification[];
  loading: boolean;
  onMarkAllRead: () => void;
  onClose: () => void;
}

function getNotificationIcon(type: Notification['type']) {
  switch (type) {
    case 'reaction':
      return <Heart className="w-4 h-4 text-red-400" />;
    case 'connection':
      return <UserPlus className="w-4 h-4 text-owl-400" />;
    case 'scene_post':
      return <FileText className="w-4 h-4 text-blue-400" />;
    default:
      return <FileText className="w-4 h-4 text-gray-400" />;
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

export default function NotificationPanel({
  notifications,
  loading,
  onMarkAllRead,
  onClose
}: NotificationPanelProps) {
  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="absolute left-0 top-12 w-96 bg-gray-900 border border-gray-800 rounded-lg shadow-xl z-50 max-h-[600px] flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-gray-800 flex items-center justify-between">
          <h3 className="font-semibold text-lg">Notifications</h3>
          <div className="flex items-center gap-2">
            {notifications.some(n => !n.is_read) && (
              <button
                onClick={onMarkAllRead}
                className="text-sm text-owl-400 hover:text-owl-300"
              >
                Mark all read
              </button>
            )}
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-white"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="p-8 text-center text-gray-400">
              Loading...
            </div>
          ) : notifications.length === 0 ? (
            <div className="p-8 text-center text-gray-400">
              No notifications yet
            </div>
          ) : (
            <div className="divide-y divide-gray-800">
              {notifications.map(notification => (
                <div
                  key={notification.id}
                  className={`p-4 hover:bg-gray-800 transition-colors ${
                    !notification.is_read ? 'bg-gray-850' : ''
                  }`}
                >
                  <div className="flex items-start gap-3">
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
          )}
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-gray-800">
          <Link
            to="/notifications"
            onClick={onClose}
            className="block text-center text-sm text-owl-400 hover:text-owl-300"
          >
            View all notifications
          </Link>
        </div>
      </div>
    </>
  );
}
