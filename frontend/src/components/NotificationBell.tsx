import { useState, useEffect } from 'react';
import { Bell } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { Notification } from '@/lib/types';
import NotificationPanel from './NotificationPanel';

export default function NotificationBell() {
  const [unreadCount, setUnreadCount] = useState(0);
  const [showPanel, setShowPanel] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchUnreadCount = async () => {
    try {
      const { count } = await apiClient.getUnreadCount();
      setUnreadCount(count);
    } catch (error) {
      console.error('Failed to fetch unread count:', error);
    }
  };

  const fetchNotifications = async () => {
    setLoading(true);
    try {
      const notifs = await apiClient.getNotifications(false, 0, 20);
      setNotifications(notifs);
    } catch (error) {
      console.error('Failed to fetch notifications:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUnreadCount();
    // Poll for new notifications every 30 seconds
    const interval = setInterval(fetchUnreadCount, 30000);
    return () => clearInterval(interval);
  }, []);

  const handleTogglePanel = async () => {
    if (!showPanel) {
      await fetchNotifications();
    }
    setShowPanel(!showPanel);
  };

  const handleMarkAllRead = async () => {
    const unreadIds = notifications.filter(n => !n.is_read).map(n => n.id);
    if (unreadIds.length === 0) return;

    try {
      await apiClient.markNotificationsRead(unreadIds);
      setNotifications(prev =>
        prev.map(n => ({ ...n, is_read: true }))
      );
      setUnreadCount(0);
    } catch (error) {
      console.error('Failed to mark notifications as read:', error);
    }
  };

  const handleClosePanel = () => {
    setShowPanel(false);
  };

  return (
    <div className="relative">
      <button
        onClick={handleTogglePanel}
        className="relative p-2 rounded-lg hover:bg-gray-800 transition-colors"
        aria-label="Notifications"
      >
        <Bell className="w-5 h-5" />
        {unreadCount > 0 && (
          <span className="absolute top-1 right-1 w-4 h-4 bg-owl-500 rounded-full text-xs flex items-center justify-center">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {showPanel && (
        <NotificationPanel
          notifications={notifications}
          loading={loading}
          onMarkAllRead={handleMarkAllRead}
          onClose={handleClosePanel}
        />
      )}
    </div>
  );
}
