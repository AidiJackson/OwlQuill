// Client half of the two-sided account-sigil pin (Beta Boundary 2).
//
// `PATCH /users/me` accepts `avatar_url` only when it is byte-identical to one
// of these strings, so a drift between this file and
// backend/app/core/account_sigils.py is not a cosmetic bug — it is a save that
// fails in front of the user with no way for them to fix it.
//
// Neither side imports the other, so both derive the same SHA-256 over their
// own sorted URL set and assert the same literal. Editing the template or the
// palette on one side alone fails that side's test.
import { describe, expect, it } from 'vitest';

import {
  ACCOUNT_SIGILS,
  ACCOUNT_SIGIL_URLS,
  SIGIL_SET_DIGEST,
} from '@/lib/accountSigils';

describe('account sigils', () => {
  it('ships exactly the eight known sigils, in picker order', () => {
    expect(ACCOUNT_SIGILS.map((s) => s.id)).toEqual([
      'ember', 'tide', 'grove', 'dusk', 'rose', 'aurum', 'mist', 'sol',
    ]);
  });

  it('derives the digest the backend allowlist derives', async () => {
    // The pin itself. If this fails, the client and the server no longer agree
    // on what an account sigil IS — fix the template, do not update the digest
    // on one side.
    //
    // Web Crypto rather than node:crypto: this package has no @types/node, so
    // importing the Node builtin type-checks as an unresolved module even
    // though vitest runs it happily. `crypto.subtle` is typed by the DOM lib
    // the app already targets and is present in the test runtime.
    const bytes = new TextEncoder().encode(
      [...ACCOUNT_SIGIL_URLS].sort().join('\n')
    );
    const hash = await crypto.subtle.digest('SHA-256', bytes);
    const digest = Array.from(new Uint8Array(hash))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');
    expect(digest).toBe(SIGIL_SET_DIGEST);
  });

  it('produces self-contained data URLs with no remote reference', () => {
    // A sigil must carry its own bytes — that is the whole reason the server
    // can accept one by value. The SVG namespace declaration is the only `http`
    // in the markup and is an identifier, never fetched, so it is excluded
    // explicitly rather than by a loose "contains http" check that would either
    // fail on it or be too weak to mean anything.
    const XMLNS = 'http://www.w3.org/2000/svg';
    for (const sigil of ACCOUNT_SIGILS) {
      expect(sigil.url.startsWith('data:image/svg+xml,')).toBe(true);
      const svg = decodeURIComponent(sigil.url.slice('data:image/svg+xml,'.length));
      expect(svg.split(XMLNS).join('')).not.toMatch(/https?:/);
      expect(svg).not.toMatch(/<(script|image|foreignObject)\b/i);
    }
  });

  it('has no duplicate urls', () => {
    expect(ACCOUNT_SIGIL_URLS.size).toBe(ACCOUNT_SIGILS.length);
  });
});
