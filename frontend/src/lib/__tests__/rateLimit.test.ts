import { describe, it, expect } from 'vitest';
import {
  rateLimitMessage,
  RATE_LIMIT_FALLBACK_MESSAGE,
  RATE_LIMIT_LOGIN_MESSAGE,
} from '../rateLimit';
// Source-level assertions, matching the convention in writerWaitlist.test.ts:
// vitest runs in `node` here with no DOM environment.
import apiClientSource from '../apiClient.ts?raw';
import loginSource from '../../pages/Login.tsx?raw';
import registerSource from '../../pages/Register.tsx?raw';

describe('a throttled request never shows the user a status code', () => {
  it('prefers the sentence the server sent', () => {
    expect(rateLimitMessage(RATE_LIMIT_LOGIN_MESSAGE)).toBe(RATE_LIMIT_LOGIN_MESSAGE);
  });

  it('falls back when the body has no usable detail', () => {
    // slowapi's stock 429 body is {"error": ...} — no `detail` at all.
    expect(rateLimitMessage(undefined)).toBe(RATE_LIMIT_FALLBACK_MESSAGE);
    expect(rateLimitMessage(null)).toBe(RATE_LIMIT_FALLBACK_MESSAGE);
    expect(rateLimitMessage('   ')).toBe(RATE_LIMIT_FALLBACK_MESSAGE);
    // A 422-style array detail is not a sentence.
    expect(rateLimitMessage([{ msg: 'nope' }])).toBe(RATE_LIMIT_FALLBACK_MESSAGE);
  });

  it('never returns anything resembling "HTTP 429"', () => {
    for (const detail of [undefined, null, '', 42, {}]) {
      expect(rateLimitMessage(detail)).not.toMatch(/HTTP|429/);
    }
  });

  it('routes 429 through the helper before the bare-status branch', () => {
    // The generic branch renders `HTTP ${response.status}`; 429 must be handled
    // ahead of it or the login failure reads as "HTTP 429" again.
    const throttleBranch = apiClientSource.indexOf('response.status === 429');
    const bareStatusBranch = apiClientSource.indexOf('`HTTP ${response.status}`');
    expect(throttleBranch).toBeGreaterThan(-1);
    expect(throttleBranch).toBeLessThan(bareStatusBranch);
    expect(apiClientSource).toContain('rateLimitMessage');
  });
});

describe('public auth surfaces carry the locked positioning', () => {
  it('states the tagline on Login and Register', () => {
    expect(loginSource).toContain('The social network for fictional characters');
    expect(registerSource).toContain('The social network for fictional characters');
  });

  it('has dropped the superseded roleplay-first tagline', () => {
    expect(loginSource).not.toContain('Roleplay-first social network');
    expect(registerSource).not.toContain('Roleplay-first social network');
  });
});
