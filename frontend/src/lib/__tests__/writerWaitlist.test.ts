import { describe, it, expect } from 'vitest';
// Source-level assertions, matching the convention in writerUnlock.test.ts:
// vitest runs in `node` here with no DOM environment, so the facts worth
// protecting are checked against the source rather than a rendered tree.
import becomeAWriterSource from '../../pages/BecomeAWriter.tsx?raw';
import profileSource from '../../pages/Profile.tsx?raw';
import layoutSource from '../../components/Layout.tsx?raw';
import commentSectionSource from '../../components/CommentSection.tsx?raw';

describe('the Writer waitlist is interest, never entitlement', () => {
  it('offers a one-click join with no email form', () => {
    expect(becomeAWriterSource).toContain('joinWriterWaitlist');
    // An email input would defeat "no extra email form" — the account is known.
    expect(becomeAWriterSource).not.toContain('type="email"');
  });

  it('confirms membership in the words the product asked for', () => {
    expect(becomeAWriterSource).toContain("You're on the Writer waitlist.");
  });

  it('lets a waitlisted account withdraw', () => {
    expect(becomeAWriterSource).toContain('leaveWriterWaitlist');
  });

  it('still refuses to fake availability', () => {
    expect(becomeAWriterSource).toContain(
      "Writer Unlock isn't available during the closed beta."
    );
    const lower = becomeAWriterSource.toLowerCase();
    expect(lower).not.toContain('unlocked!');
  });

  it('never routes into character creation from the locked branch', () => {
    const locked = becomeAWriterSource.slice(becomeAWriterSource.indexOf(') : ('));
    expect(locked).not.toContain('/characters/new');
  });
});

describe('the Become a Writer card is a single accessible control', () => {
  const card = profileSource.slice(
    profileSource.indexOf('{!isWriter && ('),
    profileSource.indexOf('{/* Security */}'),
  );

  it('is a real button, so Enter/Space and focus come for free', () => {
    expect(card).toContain('<button');
    expect(card).toContain('type="button"');
    expect(card).toContain('focus-visible:ring');
  });

  it('routes only to the upgrade gate, never straight into creation', () => {
    expect(card).toContain("navigate('/become-a-writer')");
    expect(card).not.toContain('/characters/new');
  });

  it('does not nest a second button inside the card', () => {
    // A button inside a button is invalid markup and breaks keyboard order.
    expect(card.match(/<button/g) ?? []).toHaveLength(1);
  });
});

describe('Wanderer navigation wording', () => {
  it('says "Browse Characters" for a Wanderer and keeps the route', () => {
    expect(layoutSource).toContain("isCreator ? 'Characters' : 'Browse Characters'");
    expect(layoutSource).toContain('to="/characters"');
  });
});

describe('the comment control announces comments before they are fetched', () => {
  it('uses the server-sent count, not the lazily-loaded array, when collapsed', () => {
    // The regression: `comments.length` is 0 until the section is expanded, so
    // a collapsed section always read a bare "Comments" and an existing
    // comment looked like no comment at all.
    expect(commentSectionSource).toContain('commentCount');
    expect(commentSectionSource).toContain(
      'const shownCount = loaded ? comments.length : commentCount ?? 0;',
    );
    expect(commentSectionSource).not.toContain(
      '`Comments${comments.length > 0 ? ` (${comments.length})` : \'\'}`',
    );
  });
});
