import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { Notification } from '@/lib/types';

function parsePayload(raw?: string): Record<string, unknown> {
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function NotificationItem({
  notif,
  onRead,
}: {
  notif: Notification;
  onRead: (id: number) => void;
}) {
  const navigate = useNavigate();
  const payload = parsePayload(notif.payload);

  const handleClick = async () => {
    if (!notif.is_read) {
      onRead(notif.id);
      await apiClient.markNotificationRead(notif.id).catch(() => null);
    }
    if (notif.type === 'mention' && payload.post_id) {
      // Navigate to the feed — deeplink to specific post not yet implemented
      navigate('/');
    }
  };

  const renderBody = () => {
    if (notif.type === 'mention') {
      // Identity-first: notifications identify the authoring CHARACTER.
      // Legacy payloads (pre-Sprint 33) stored the account username — never
      // render it; fall back to a neutral "Someone".
      const authorCharacter = payload.author_character_name as string | undefined;
      const mention = payload.mention_text as string | undefined;
      const preview = payload.post_preview as string | undefined;
      return (
        <div>
          <p className="text-sm text-white/90">
            <span className="font-semibold text-violet-400">{authorCharacter ?? 'Someone'}</span>{' '}
            mentioned {mention ? <span className="text-violet-400">{mention}</span> : 'you'} in a post
          </p>
          {preview && (
            <p className="mt-1 text-xs text-white/50 line-clamp-2">{preview}</p>
          )}
        </div>
      );
    }
    return (
      <p className="text-sm text-white/90 capitalize">{notif.type.replace(/_/g, ' ')}</p>
    );
  };

  return (
    <div
      onClick={handleClick}
      className={`flex items-start gap-3 p-4 rounded-xl border cursor-pointer transition-colors ${
        notif.is_read
          ? 'bg-[#1A1D23]/30 border-[#2D3139]/40 hover:bg-[#1A1D23]/50'
          : 'bg-violet-950/20 border-violet-800/30 hover:bg-violet-950/30'
      }`}
    >
      {!notif.is_read && (
        <span className="mt-1.5 w-2 h-2 rounded-full bg-violet-400 flex-shrink-0" />
      )}
      {notif.is_read && <span className="mt-1.5 w-2 h-2 flex-shrink-0" />}
      <div className="flex-1 min-w-0">
        {renderBody()}
        <p className="mt-1 text-xs text-white/30">
          {new Date(notif.created_at).toLocaleDateString(undefined, {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
          })}
        </p>
      </div>
    </div>
  );
}

export default function Notifications() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [markingAll, setMarkingAll] = useState(false);

  useEffect(() => {
    apiClient.getNotifications(50)
      .then(setNotifications)
      .catch(() => setNotifications([]))
      .finally(() => setLoading(false));
  }, []);

  const handleRead = (id: number) => {
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
    );
  };

  const handleMarkAllRead = async () => {
    setMarkingAll(true);
    try {
      await apiClient.markAllNotificationsRead();
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
    } catch {
      // silent
    } finally {
      setMarkingAll(false);
    }
  };

  const unread = notifications.filter((n) => !n.is_read).length;

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Notifications</h1>
        {unread > 0 && (
          <button
            onClick={handleMarkAllRead}
            disabled={markingAll}
            className="text-sm text-violet-400 hover:text-violet-300 transition-colors disabled:opacity-50"
          >
            {markingAll ? 'Marking…' : 'Mark all read'}
          </button>
        )}
      </div>

      {loading && (
        <div className="flex justify-center py-16">
          <div className="w-8 h-8 border-4 border-violet-500/30 border-t-violet-500 rounded-full animate-spin" />
        </div>
      )}

      {!loading && notifications.length === 0 && (
        <div className="text-center py-16">
          <p className="text-white/50">You have no notifications yet.</p>
        </div>
      )}

      {!loading && notifications.length > 0 && (
        <div className="space-y-2">
          {notifications.map((notif) => (
            <NotificationItem key={notif.id} notif={notif} onRead={handleRead} />
          ))}
        </div>
      )}
    </div>
  );
}
