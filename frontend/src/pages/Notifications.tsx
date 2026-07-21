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

/** Presentation-only day bucket for grouped headers (Figma-style). */
function dayLabel(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const startOfDay = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diffDays = Math.round((startOfDay(now) - startOfDay(d)) / 86_400_000);
  if (diffDays <= 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return 'This week';
  return 'Earlier';
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
          <p className="text-sm text-ink">
            <span className="font-semibold text-gem">{authorCharacter ?? 'Someone'}</span>{' '}
            mentioned {mention ? <span className="text-gem">{mention}</span> : 'you'} in a post
          </p>
          {preview && (
            <p className="mt-1 text-xs text-ink-3 line-clamp-2">{preview}</p>
          )}
        </div>
      );
    }
    return (
      <p className="text-sm text-ink capitalize">{notif.type.replace(/_/g, ' ')}</p>
    );
  };

  return (
    <div
      onClick={handleClick}
      className={`flex items-start gap-3 px-3 py-3.5 -mx-3 rounded-xl cursor-pointer transition-colors ${
        notif.is_read
          ? 'hover:bg-surface-elevated'
          : 'bg-gem-soft/60 hover:bg-gem-soft'
      }`}
    >
      {!notif.is_read && (
        <span className="mt-1.5 w-2 h-2 rounded-full bg-gem flex-shrink-0" />
      )}
      {notif.is_read && <span className="mt-1.5 w-2 h-2 flex-shrink-0" />}
      <div className="flex-1 min-w-0">
        {renderBody()}
        <p className="mt-1 font-mono text-[11px] text-ink-3">
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
    <div className="max-w-2xl mx-auto px-5 sm:px-8 py-10">
      <div className="flex items-end justify-between mb-8">
        <h1 className="font-serif text-4xl font-medium tracking-[-0.02em] text-ink">Notifications</h1>
        {unread > 0 && (
          <button
            onClick={handleMarkAllRead}
            disabled={markingAll}
            className="text-sm text-gem hover:opacity-80 transition-opacity disabled:opacity-50"
          >
            {markingAll ? 'Marking…' : 'Mark all read'}
          </button>
        )}
      </div>

      {loading && (
        <div className="flex justify-center py-16">
          <div className="w-8 h-8 border-4 border-gem/25 border-t-gem rounded-full animate-spin" />
        </div>
      )}

      {!loading && notifications.length === 0 && (
        <div className="text-center py-16">
          <p className="text-ink-3">You have no notifications yet.</p>
        </div>
      )}

      {!loading && notifications.length > 0 && (
        <div className="space-y-1">
          {notifications.map((notif, idx) => {
            const label = dayLabel(notif.created_at);
            const prevLabel = idx > 0 ? dayLabel(notifications[idx - 1].created_at) : null;
            return (
              <div key={notif.id}>
                {label !== prevLabel && (
                  <h2 className="font-mono text-[11px] uppercase tracking-[0.1em] text-ink-3 pt-5 pb-2 first:pt-0">
                    {label}
                  </h2>
                )}
                <NotificationItem notif={notif} onRead={handleRead} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
