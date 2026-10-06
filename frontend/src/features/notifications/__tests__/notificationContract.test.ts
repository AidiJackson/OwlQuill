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
  it('says the author character tagged your character in a post, and goes to that exact post', () => {
    const view = describeNotification({ type: 'character_tagged', payload: tagged });
    expect(view.kind).toBe('character_tagged');
    expect(view.actorName).toBe('Bram');
    expect(view.recipientCharacterName).toBe('Elowen');
    expect(view.summary).toBe('Bram tagged Elowen in a post in The Glass Market');
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
    expect(view.summary).toBe('Bram tagged Elowen in a post');
    expect(view.preview).toBeNull();
    expect(view.realmName).toBeNull();
    expect(notificationDestination(view.target)).toBe('/posts/77');
  });

  it('never borrows mention keys or an account name; falls back neutrally', () => {
    const odd = JSON.stringify({ post_id: 5, author_username: 'aidan', mentioned_character_name: 'Nope' });
    const view = describeNotification({ type: 'character_tagged', payload: odd });
    expect(view.actorName).toBe(UNKNOWN_ACTOR);
    expect(view.summary).toBe('Someone tagged one of your characters in a post');
    expect(view.summary).not.toContain('aidan');
    expect(view.summary).not.toContain('Nope');
  });

  it('a malformed row has nowhere to go', () => {
    const view = describeNotification({ type: 'character_tagged', payload: '{bad' });
    expect(view.target).toBeNull();
    expect(notificationDestination(view.target)).toBeNull();
  });
});
