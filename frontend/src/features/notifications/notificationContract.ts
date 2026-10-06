/**
 * Notifications — the typed reading side of the payload contract (Phase 7.1).
 *
 * The server stores each notification's context as JSON text whose keys are
 * documented in backend/app/services/notifications.py. This module is the ONE
 * place that text becomes product language and a destination, so the page
 * never renders a raw `type` string or trusts a payload key it has not
 * checked. Pure and DOM-free so it runs in the node vitest environment.
 *
 * `character_tagged` (W-10A) — the live producer: a post's author explicitly
 * tagged one of the recipient's characters. User-facing copy says "featured"
 * (the product word for an explicit tag); the type name is unchanged. Ids + name snapshots for the
 * author and tagged characters, realm id, and realm name + preview only when
 * the recipient may see the post.
 *
 * `mention` is LEGACY — typed @mentions stopped notifying in W-10A — but
 * historical rows still render. Three generations of its payload:
 *   • 7.1  — author + mentioned character ids/names, realm id (+ name and
 *            preview when the recipient may see them).
 *   • Sprint 33 — author character name, `mention_text`, preview.
 *   • pre-33 — an account username (never shown; falls back to "Someone").
 */
import type { Notification } from '@/lib/types';

/** What a notification points at. Only posts today; 7.2 adds more. */
export type NotificationTarget = { kind: 'post'; postId: number };

export interface NotificationView {
  /** The producer's type, or 'unknown' for anything this build cannot read. */
  kind: 'character_tagged' | 'mention' | 'unknown';
  /** The acting character, or a neutral stand-in — never an account name. */
  actorName: string;
  /** The recipient's character that was tagged (or, legacy, addressed). */
  recipientCharacterName: string | null;
  /** "in <Realm>" context, only when the server chose to include it. */
  realmName: string | null;
  /** The sentence shown on the row, fully resolved. */
  summary: string;
  /** Post excerpt, present only when the recipient may see the post. */
  preview: string | null;
  target: NotificationTarget | null;
}

type Payload = Record<string, unknown>;

/** Parse the payload text; any failure is an empty object, never a throw. */
export function parseNotificationPayload(raw: string | null | undefined): Payload {
  if (!raw) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Payload) : {};
  } catch {
    return {};
  }
}

function str(payload: Payload, key: string): string | null {
  const v = payload[key];
  return typeof v === 'string' && v.trim() ? v : null;
}

function int(payload: Payload, key: string): number | null {
  const v = payload[key];
  return typeof v === 'number' && Number.isInteger(v) && v > 0 ? v : null;
}

/** Neutral copy for a type this build does not know how to read. */
export const UNKNOWN_NOTIFICATION_SUMMARY = 'Something new happened around one of your characters.';

/** Stand-in for an actor whose character identity the row does not carry. */
export const UNKNOWN_ACTOR = 'Someone';

/**
 * Resolve one row into what the page shows and where it goes.
 *
 * Copy is character-first: "<Actor> mentioned <Character> in <Realm>". When
 * the recipient side is unknown (legacy rows) it says "one of your
 * characters" rather than "you" — the account was never the one addressed.
 */
export function describeNotification(notif: Pick<Notification, 'type' | 'payload'>): NotificationView {
  const payload = parseNotificationPayload(notif.payload);

  if (notif.type === 'character_tagged') {
    const actorName = str(payload, 'author_character_name') ?? UNKNOWN_ACTOR;
    const recipientCharacterName = str(payload, 'tagged_character_name');
    const realmName = str(payload, 'realm_name');
    const postId = int(payload, 'post_id');

    const who = recipientCharacterName ?? 'one of your characters';
    const where = realmName ? ` in a post in ${realmName}` : ' in a post';
    return {
      kind: 'character_tagged',
      actorName,
      recipientCharacterName,
      realmName,
      summary: `${actorName} featured ${who}${where}`,
      preview: str(payload, 'post_preview'),
      target: postId ? { kind: 'post', postId } : null,
    };
  }

  if (notif.type === 'mention') {
    const actorName = str(payload, 'author_character_name') ?? UNKNOWN_ACTOR;
    // 7.1 rows name the character; Sprint 33 rows carry only the literal
    // "@Handle" as written, which is still that character's name.
    const recipientCharacterName =
      str(payload, 'mentioned_character_name') ?? str(payload, 'mention_text')?.replace(/^@/, '') ?? null;
    const realmName = str(payload, 'realm_name');
    const postId = int(payload, 'post_id');

    const who = recipientCharacterName ?? 'one of your characters';
    const where = realmName ? ` in ${realmName}` : ' in a post';
    return {
      kind: 'mention',
      actorName,
      recipientCharacterName,
      realmName,
      summary: `${actorName} mentioned ${who}${where}`,
      preview: str(payload, 'post_preview'),
      target: postId ? { kind: 'post', postId } : null,
    };
  }

  // A type from a newer server (or a stray row). Say something true and
  // neutral; never the internal type string, never guessed detail.
  return {
    kind: 'unknown',
    actorName: UNKNOWN_ACTOR,
    recipientCharacterName: null,
    realmName: null,
    summary: UNKNOWN_NOTIFICATION_SUMMARY,
    preview: null,
    target: null,
  };
}

/** The route for a target, or null when the row has nowhere to go. */
export function notificationDestination(target: NotificationTarget | null): string | null {
  if (!target) return null;
  switch (target.kind) {
    case 'post':
      return `/posts/${target.postId}`;
    default:
      return null;
  }
}
