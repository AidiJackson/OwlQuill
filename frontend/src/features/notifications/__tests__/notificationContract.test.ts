/**
 * The notification payload contract, read side — Polish Phase 7.1.
 *
 * Pure functions, node environment. Three generations of `mention` payload
 * and every kind of bad input must come out as product copy and a typed
 * destination — never a raw type string, never an account username.
 */
import { describe, expect, it } from 'vitest';
import {
  UNKNOWN_ACTOR,
  UNKNOWN_NOTIFICATION_SUMMARY,
  WANDERER_ACTOR,
  describeNotification,
  notificationDestination,
  parseNotificationPayload,
} from '../notificationContract';

const v71 = JSON.stringify({
  post_id: 42,
  realm_id: 7,
  realm_name: 'The Glass Market',
  author_character_id: 3,
  author_character_name: 'Bram',
  mentioned_character_id: 9,
  mentioned_character_name: 'Elowen',
  mention_text: '@Elowen',
  post_preview: 'At the gate, @Elowen turned…',
});

describe('parseNotificationPayload', () => {
  it('returns an object for valid JSON and {} for everything else', () => {
    expect(parseNotificationPayload(v71)).toMatchObject({ post_id: 42 });
    expect(parseNotificationPayload(undefined)).toEqual({});
    expect(parseNotificationPayload(null)).toEqual({});
    expect(parseNotificationPayload('')).toEqual({});
    expect(parseNotificationPayload('{not json')).toEqual({});
    expect(parseNotificationPayload('[1,2]')).toEqual({});
    expect(parseNotificationPayload('"a string"')).toEqual({});
  });
});

describe('describeNotification — mention', () => {
  it('7.1 payload: character-first copy with recipient character and realm', () => {
    const view = describeNotification({ type: 'mention', payload: v71 });
    expect(view.kind).toBe('mention');
    expect(view.actorName).toBe('Bram');
    expect(view.recipientCharacterName).toBe('Elowen');
    expect(view.realmName).toBe('The Glass Market');
    expect(view.summary).toBe('Bram mentioned Elowen in The Glass Market');
    expect(view.preview).toBe('At the gate, @Elowen turned…');
    expect(view.target).toEqual({ kind: 'post', postId: 42 });
  });

  it('7.1 payload with preview withheld (private realm): copy still truthful, no excerpt, no realm name', () => {
    const withheld = JSON.stringify({
      post_id: 42, realm_id: 7,
      author_character_id: 3, author_character_name: 'Bram',
      mentioned_character_id: 9, mentioned_character_name: 'Elowen', mention_text: '@Elowen',
    });
    const view = describeNotification({ type: 'mention', payload: withheld });
    expect(view.summary).toBe('Bram mentioned Elowen in a post');
    expect(view.preview).toBeNull();
    expect(view.realmName).toBeNull();
    expect(view.target).toEqual({ kind: 'post', postId: 42 });
  });

  it('Sprint 33 legacy payload: author name + @handle, no ids beyond post', () => {
    const legacy = JSON.stringify({
      post_id: 11, author_character_id: 3, author_character_name: 'Bram',
      mention_text: '@Elowen', post_preview: 'old preview', target_type: 'character',
    });
    const view = describeNotification({ type: 'mention', payload: legacy });
    expect(view.summary).toBe('Bram mentioned Elowen in a post');
    expect(view.preview).toBe('old preview');
    expect(view.target).toEqual({ kind: 'post', postId: 11 });
  });

  it('pre-Sprint-33 payload with an account username: never shown, neutral actor instead', () => {
    const ancient = JSON.stringify({ post_id: 5, author_username: 'aidan_j', mention_text: '@Elowen' });
    const view = describeNotification({ type: 'mention', payload: ancient });
    expect(view.actorName).toBe(UNKNOWN_ACTOR);
    expect(view.summary).toBe('Someone mentioned Elowen in a post');
    expect(JSON.stringify(view)).not.toContain('aidan_j');
    expect(view.target).toEqual({ kind: 'post', postId: 5 });
  });

  it('malformed or empty payload: still a sentence about a character, nowhere to go', () => {
    for (const payload of [undefined, '', '{bad', '{}', JSON.stringify({ post_id: 'x' })]) {
      const view = describeNotification({ type: 'mention', payload });
      expect(view.kind).toBe('mention');
      expect(view.summary).toBe('Someone mentioned one of your characters in a post');
      expect(view.summary).not.toMatch(/\byou\b/);
      expect(view.target).toBeNull();
      expect(view.preview).toBeNull();
    }
  });

  it('ignores a post_id that is not a positive integer', () => {
    expect(describeNotification({ type: 'mention', payload: JSON.stringify({ post_id: 0 }) }).target).toBeNull();
    expect(describeNotification({ type: 'mention', payload: JSON.stringify({ post_id: -3 }) }).target).toBeNull();
    expect(describeNotification({ type: 'mention', payload: JSON.stringify({ post_id: 2.5 }) }).target).toBeNull();
    expect(describeNotification({ type: 'mention', payload: JSON.stringify({ post_id: '42' }) }).target).toBeNull();
  });
});

describe('describeNotification — unknown types', () => {
  it('never exposes the internal type string', () => {
    for (const type of ['new_comment', 'story_space_invite', 'DM_RECEIVED', 'weird-type-3']) {
      const view = describeNotification({ type, payload: JSON.stringify({ post_id: 1, anything: 'x' }) });
      expect(view.kind).toBe('unknown');
      expect(view.summary).toBe(UNKNOWN_NOTIFICATION_SUMMARY);
      expect(view.summary.toLowerCase()).not.toContain(type.toLowerCase());
      expect(view.summary).not.toMatch(/_/);
      expect(view.target).toBeNull();
      expect(view.preview).toBeNull();
    }
  });
});

describe('notificationDestination', () => {
  it('routes a post target to the post page and nothing to nowhere', () => {
    expect(notificationDestination({ kind: 'post', postId: 42 })).toBe('/posts/42');
    expect(notificationDestination(null)).toBeNull();
  });
});

// ── W-10A: character_tagged ───────────────────────────────────────────────

const tagged = JSON.stringify({
  post_id: 77,
  realm_id: 7,
  realm_name: 'The Glass Market',
  author_character_id: 3,
  author_character_name: 'Bram',
  tagged_character_id: 9,
  tagged_character_name: 'Elowen',
  post_preview: 'At the gate, Elowen turned…',
});

describe('describeNotification — character_tagged', () => {
  it('says the author character featured your character in a post, and goes to that exact post', () => {
    const view = describeNotification({ type: 'character_tagged', payload: tagged });
    expect(view.kind).toBe('character_tagged');
    expect(view.actorName).toBe('Bram');
    expect(view.recipientCharacterName).toBe('Elowen');
    expect(view.summary).toBe('Bram featured Elowen in a post in The Glass Market');
    expect(view.preview).toBe('At the gate, Elowen turned…');
    expect(view.target).toEqual({ kind: 'post', postId: 77 });
    expect(notificationDestination(view.target)).toBe('/posts/77');
  });

  it('preview withheld (private realm): truthful copy, no excerpt, no realm name', () => {
    const withheld = JSON.stringify({
      post_id: 77, realm_id: 7,
      author_character_id: 3, author_character_name: 'Bram',
      tagged_character_id: 9, tagged_character_name: 'Elowen',
    });
    const view = describeNotification({ type: 'character_tagged', payload: withheld });
    expect(view.summary).toBe('Bram featured Elowen in a post');
    expect(view.preview).toBeNull();
    expect(view.realmName).toBeNull();
    expect(notificationDestination(view.target)).toBe('/posts/77');
  });

  it('never borrows mention keys or an account name; falls back neutrally', () => {
    const odd = JSON.stringify({ post_id: 5, author_username: 'aidan', mentioned_character_name: 'Nope' });
    const view = describeNotification({ type: 'character_tagged', payload: odd });
    expect(view.actorName).toBe(UNKNOWN_ACTOR);
    expect(view.summary).toBe('Someone featured one of your characters in a post');
    expect(view.summary).not.toContain('aidan');
    expect(view.summary).not.toContain('Nope');
  });

  it('a malformed row has nowhere to go', () => {
    const view = describeNotification({ type: 'character_tagged', payload: '{bad' });
    expect(view.target).toBeNull();
    expect(notificationDestination(view.target)).toBeNull();
  });
});

// ── 7.2A: post_commented ──────────────────────────────────────────────────

const commented = JSON.stringify({
  post_id: 88,
  realm_id: 7,
  comment_id: 501,
  commenter_kind: 'character',
  commenter_character_id: 4,
  commenter_character_name: 'Mara',
  post_character_id: 9,
  post_character_name: 'Angelo',
  realm_name: 'Ashfall',
  comment_preview: 'The lanterns were never lit.',
});

describe('describeNotification — post_commented', () => {
  it("says which character commented on which of your characters' posts, and goes to that exact post", () => {
    const view = describeNotification({ type: 'post_commented', payload: commented });
    expect(view.kind).toBe('post_commented');
    expect(view.actorName).toBe('Mara');
    expect(view.recipientCharacterName).toBe('Angelo');
    expect(view.summary).toBe("Mara commented on Angelo's post in Ashfall");
    expect(view.preview).toBe('The lanterns were never lit.');
    expect(view.target).toEqual({ kind: 'post', postId: 88 });
    expect(notificationDestination(view.target)).toBe('/posts/88');
  });

  it('preview withheld (realm no longer accessible): truthful copy, no excerpt, no realm name', () => {
    const withheld = JSON.stringify({
      post_id: 88, realm_id: 7, comment_id: 501, commenter_kind: 'character',
      commenter_character_id: 4, commenter_character_name: 'Mara',
      post_character_id: 9, post_character_name: 'Angelo',
    });
    const view = describeNotification({ type: 'post_commented', payload: withheld });
    expect(view.summary).toBe("Mara commented on Angelo's post");
    expect(view.preview).toBeNull();
    expect(view.realmName).toBeNull();
    expect(notificationDestination(view.target)).toBe('/posts/88');
  });

  it('a Wanderer commenter is "A Wanderer", never an account name', () => {
    const wanderer = JSON.stringify({
      post_id: 88, realm_id: 7, comment_id: 502, commenter_kind: 'wanderer',
      author_username: 'drifter_99', post_character_name: 'Angelo', comment_preview: 'Passing through.',
    });
    const view = describeNotification({ type: 'post_commented', payload: wanderer });
    expect(view.actorName).toBe(WANDERER_ACTOR);
    expect(view.summary).toBe("A Wanderer commented on Angelo's post");
    expect(view.summary).not.toContain('drifter_99');
  });

  it("without the post's character it says \"your post\"; without an actor, \"Someone\"", () => {
    const sparse = JSON.stringify({ post_id: 88 });
    const view = describeNotification({ type: 'post_commented', payload: sparse });
    expect(view.actorName).toBe(UNKNOWN_ACTOR);
    expect(view.summary).toBe('Someone commented on your post');
    expect(notificationDestination(view.target)).toBe('/posts/88');
  });

  it('never borrows tag or mention keys', () => {
    const odd = JSON.stringify({ post_id: 5, author_character_name: 'Bram', tagged_character_name: 'Elowen' });
    const view = describeNotification({ type: 'post_commented', payload: odd });
    expect(view.summary).toBe('Someone commented on your post');
  });

  it('a malformed row has nowhere to go', () => {
    const view = describeNotification({ type: 'post_commented', payload: '{bad' });
    expect(view.target).toBeNull();
    expect(notificationDestination(view.target)).toBeNull();
  });
});

// ── 7.2B: message_received ────────────────────────────────────────────────

const messaged = (count?: number) =>
  JSON.stringify({
    conversation_id: 12,
    sender_character_id: 4,
    sender_character_name: 'Mara',
    recipient_character_id: 9,
    recipient_character_name: 'Angelo',
    ...(count === undefined ? {} : { message_count: count }),
  });

describe('describeNotification — message_received', () => {
  it('one message: says who messaged which character, and goes to that conversation', () => {
    const view = describeNotification({ type: 'message_received', payload: messaged(1) });
    expect(view.kind).toBe('message_received');
    expect(view.actorName).toBe('Mara');
    expect(view.recipientCharacterName).toBe('Angelo');
    expect(view.summary).toBe('Mara sent Angelo a message');
    expect(view.target).toEqual({ kind: 'conversation', conversationId: 12 });
    expect(notificationDestination(view.target)).toBe('/messages/12');
  });

  it('a grouped row counts its messages', () => {
    expect(describeNotification({ type: 'message_received', payload: messaged(3) }).summary)
      .toBe('Mara sent Angelo 3 messages');
    // A missing or invalid count reads as one message.
    expect(describeNotification({ type: 'message_received', payload: messaged() }).summary)
      .toBe('Mara sent Angelo a message');
  });

  it('never shows message text, even if a payload carried some', () => {
    const leaky = JSON.stringify({
      conversation_id: 12, sender_character_name: 'Mara', recipient_character_name: 'Angelo',
      message_count: 1, body: 'secret', preview: 'secret', comment_preview: 'secret', post_preview: 'secret',
    });
    const view = describeNotification({ type: 'message_received', payload: leaky });
    expect(view.preview).toBeNull();
    expect(view.realmName).toBeNull();
    expect(JSON.stringify(view)).not.toContain('secret');
  });

  it('missing names fall back neutrally and never to an account name', () => {
    const sparse = JSON.stringify({ conversation_id: 12, sender_username: 'mara_acct' });
    const view = describeNotification({ type: 'message_received', payload: sparse });
    expect(view.summary).toBe('Someone sent one of your characters a message');
    expect(view.summary).not.toContain('mara_acct');
  });

  it('a malformed row has nowhere to go', () => {
    const view = describeNotification({ type: 'message_received', payload: '{bad' });
    expect(view.target).toBeNull();
    expect(notificationDestination(view.target)).toBeNull();
  });
});

describe('notificationDestination — conversation', () => {
  it('routes a conversation target to its thread', () => {
    expect(notificationDestination({ kind: 'conversation', conversationId: 5 })).toBe('/messages/5');
  });
});
