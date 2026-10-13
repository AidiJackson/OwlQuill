/**
 * One in-page signal that unread state changed (Phase 7.2B).
 *
 * Layout owns the Notifications badge and the Messages indicator and refetches
 * both on navigation. A page that changes unread state WITHOUT a navigation —
 * the conversation thread marking its messages read — announces it here so the
 * indicators update at once. No polling: this only fires on the viewer's own
 * actions.
 */
export const UNREAD_CHANGED_EVENT = 'ficshon:unread-changed';

export function announceUnreadChanged(): void {
  window.dispatchEvent(new Event(UNREAD_CHANGED_EVENT));
}
