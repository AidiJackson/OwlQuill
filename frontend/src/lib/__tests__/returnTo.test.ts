import { describe, it, expect } from 'vitest';
import {
  DEFAULT_RETURN_TO,
  buildReturnTo,
  returnToFromState,
  safeReturnTo,
} from '../returnTo';

describe('buildReturnTo', () => {
  it('keeps the pathname, search and hash of a deep link', () => {
    expect(
      buildReturnTo({ pathname: '/characters/59', search: '?tab=media', hash: '#foo' })
    ).toBe('/characters/59?tab=media#foo');
  });

  it('handles a bare pathname', () => {
    expect(buildReturnTo({ pathname: '/characters/59' })).toBe('/characters/59');
    expect(buildReturnTo({ pathname: '/characters/59', search: '', hash: '' })).toBe(
      '/characters/59'
    );
  });
});

describe('safeReturnTo — internal destinations survive', () => {
  it('accepts an ordinary in-app path', () => {
    expect(safeReturnTo('/characters/59')).toBe('/characters/59');
  });

  it('accepts search parameters', () => {
    expect(safeReturnTo('/characters/59?tab=media')).toBe('/characters/59?tab=media');
  });

  it('accepts a hash', () => {
    expect(safeReturnTo('/characters/59#gallery')).toBe('/characters/59#gallery');
  });

  it('accepts pathname, search and hash together', () => {
    expect(safeReturnTo('/characters/59?tab=media#foo')).toBe('/characters/59?tab=media#foo');
  });

  it('accepts a path that merely starts with an auth route name', () => {
    expect(safeReturnTo('/loginsomething')).toBe('/loginsomething');
    expect(safeReturnTo('/register-interest')).toBe('/register-interest');
  });
});

describe('safeReturnTo — open-redirect protection', () => {
  it('rejects an absolute external URL', () => {
    expect(safeReturnTo('https://evil.example')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('http://evil.example/path')).toBe(DEFAULT_RETURN_TO);
  });

  it('rejects a protocol-relative URL', () => {
    expect(safeReturnTo('//evil.example')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('//evil.example/characters/59')).toBe(DEFAULT_RETURN_TO);
  });

  it('rejects a backslash-disguised protocol-relative URL', () => {
    // Browsers normalise the backslash to a slash, so this is `//evil.example`
    // by the time it is navigated.
    expect(safeReturnTo('/\\evil.example')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('\\\\evil.example')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('/\\/evil.example')).toBe(DEFAULT_RETURN_TO);
  });

  it('rejects control characters browsers would strip', () => {
    expect(safeReturnTo('/\t/evil.example')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('/\n/evil.example')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('/\r/evil.example')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('\t//evil.example')).toBe(DEFAULT_RETURN_TO);
  });

  it('rejects raw whitespace', () => {
    expect(safeReturnTo(' /characters/59')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('/characters/ 59')).toBe(DEFAULT_RETURN_TO);
  });

  it('rejects other schemes', () => {
    expect(safeReturnTo('javascript:alert(1)')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('data:text/html,<script>')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('mailto:someone@evil.example')).toBe(DEFAULT_RETURN_TO);
  });

  it('rejects a relative path with no leading slash', () => {
    expect(safeReturnTo('characters/59')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('../characters/59')).toBe(DEFAULT_RETURN_TO);
  });
});

describe('safeReturnTo — loop protection', () => {
  it('rejects the auth routes themselves', () => {
    expect(safeReturnTo('/login')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('/register')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('/forgot-password')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('/reset-password')).toBe(DEFAULT_RETURN_TO);
  });

  it('rejects an auth route carrying search or hash', () => {
    expect(safeReturnTo('/login?next=/x')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('/reset-password?token=abc')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('/login#anchor')).toBe(DEFAULT_RETURN_TO);
  });

  it('rejects an auth route in any casing, because the router matches that way', () => {
    expect(safeReturnTo('/Login')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('/LOGIN')).toBe(DEFAULT_RETURN_TO);
  });
});

describe('safeReturnTo — missing and malformed input', () => {
  it('falls back for anything that is not a non-empty string', () => {
    expect(safeReturnTo(undefined)).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo(null)).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo('')).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo(42)).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo({ from: '/characters/59' })).toBe(DEFAULT_RETURN_TO);
    expect(safeReturnTo(['/characters/59'])).toBe(DEFAULT_RETURN_TO);
  });
});

describe('returnToFromState', () => {
  it('reads and validates a destination out of router location state', () => {
    expect(returnToFromState({ from: '/characters/59?tab=media#foo' })).toBe(
      '/characters/59?tab=media#foo'
    );
  });

  it('falls back when state is absent, empty or hostile', () => {
    expect(returnToFromState(null)).toBe(DEFAULT_RETURN_TO);
    expect(returnToFromState(undefined)).toBe(DEFAULT_RETURN_TO);
    expect(returnToFromState({})).toBe(DEFAULT_RETURN_TO);
    expect(returnToFromState({ from: 'https://evil.example' })).toBe(DEFAULT_RETURN_TO);
    expect(returnToFromState({ from: '//evil.example' })).toBe(DEFAULT_RETURN_TO);
  });
});
