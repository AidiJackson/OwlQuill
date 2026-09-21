import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { Notification } from '@/lib/types';
import InlineNotice from '@/components/InlineNotice';
import { describeNotification, notificationDestination } from '@/features/notifications/notificationContract';

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

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * One row. A real link when the notification has somewhere to go, a button
 * when it only has something to say — either way reachable by keyboard and
 * announced with its own text, which the old clickable div was not.
 *
 * Reading is optimistic and fire-and-forget: the row flips to read locally
 * and the PATCH is sent without being awaited, so a slow or failed request
 * never stands between the user and the content they clicked.
 */
function NotificationItem({
  notif,
  onRead,
}: {
  notif: Notification;
  onRead: (id: number) => void;
}) {
  const view = describeNotification(notif);
  const destination = notificationDestination(view.target);

  const markRead = () => {
    if (notif.is_read) return;
    onRead(notif.id);
    void apiClient.markNotificationRead(notif.id).catch(() => null);
  };

  const rowCls = `flex items-start gap-3 w-full text-left px-3 py-3.5 -mx-3 rounded-xl transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-gem/60 ${
    notif.is_read ? 'hover:bg-surface-elevated' : 'bg-gem/[0.06] hover:bg-gem-soft'
  }`;

  const body = (
    <>
      <span aria-hidden="true" className={`mt-1.5 w-2 h-2 rounded-full flex-shrink-0 ${notif.is_read ? '' : 'bg-gem'}`} />
      <span className="flex-1 min-w-0 block">
        {!notif.is_read && <span className="sr-only">Unread. </span>}
        <span className="block text-sm text-ink">
          {view.kind === 'unknown' ? (
            view.summary
          ) : (
            <>
              <span className="font-semibold text-gem">{view.actorName}</span>
              {view.summary.slice(view.actorName.length)}
            </>
          )}
        </span>
        {view.preview && (
          <span className="block mt-1 text-xs text-ink-3 line-clamp-2">{view.preview}</span>
        )}
        <span className="block mt-1 font-mono text-[11px] text-ink-3">{formatWhen(notif.created_at)}</span>
      </span>
    </>
  );

  if (destination) {
    return (
      <Link to={destination} onClick={markRead} className={rowCls}>
        {body}
      </Link>
    );
  }
  return (
    <button type="button" onClick={markRead} className={rowCls}>
      {body}
    </button>
  );
}

export default function Notifications() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [markingAll, setMarkingAll] = useState(false);
  const [markAllError, setMarkAllError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    apiClient
      .getNotifications(50)
      .then(setNotifications)
      .catch(() => {
        // Say so. An empty list and a failed request are different facts,
        // and "You have no notifications yet" is only true for one of them.
        setNotifications([]);
        setLoadError("Couldn't load your notifications.");
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleRead = (id: number) => {
    setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, is_read: true } : n)));
  };

  const handleMarkAllRead = async () => {
    setMarkingAll(true);
    setMarkAllError(null);
    try {
      await apiClient.markAllNotificationsRead();
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
    } catch {
      setMarkAllError("Couldn't mark everything read. Try again.");
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
            type="button"
            onClick={handleMarkAllRead}
            disabled={markingAll}
            className="text-sm text-gem hover:opacity-80 transition-opacity disabled:opacity-50"
          >
            {markingAll ? 'Marking…' : 'Mark all read'}
          </button>
        )}
      </div>

      {markAllError && (
        <InlineNotice tone="error" className="mb-4" onDismiss={() => setMarkAllError(null)}>
          {markAllError}
        </InlineNotice>
      )}

      {loading && (
        <div className="flex justify-center py-16" role="status" aria-label="Loading notifications">
          <div className="w-8 h-8 border-4 border-gem/25 border-t-gem rounded-full animate-spin" />
        </div>
      )}

      {!loading && loadError && (
        <InlineNotice tone="error">
          <span>{loadError} </span>
          <button type="button" onClick={load} className="underline underline-offset-2 hover:opacity-80">
            Try again
          </button>
        </InlineNotice>
      )}

      {!loading && !loadError && notifications.length === 0 && (
        <div className="text-center py-16">
          <p className="text-ink-3">You have no notifications yet.</p>
        </div>
      )}

      {!loading && notifications.length > 0 && (
        <ul className="space-y-1 list-none p-0 m-0">
          {notifications.map((notif, idx) => {
            const label = dayLabel(notif.created_at);
            const prevLabel = idx > 0 ? dayLabel(notifications[idx - 1].created_at) : null;
            return (
              <li key={notif.id}>
                {label !== prevLabel && (
                  <h2 className="font-mono text-[11px] uppercase tracking-[0.1em] text-ink-3 pt-5 pb-2 first:pt-0">
                    {label}
                  </h2>
                )}
                <NotificationItem notif={notif} onRead={handleRead} />
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
