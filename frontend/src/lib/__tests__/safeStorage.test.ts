// Browser storage is optional infrastructure — the failure modes, not the
// wrapper's happy path.
//
// Every case below is a real browser condition, not a hypothetical: Safari
// private browsing and site-data-blocked webviews throw on the property access
// itself; quota-full profiles throw from setItem; enterprise policy can make
// the object absent entirely. Each one used to reach React, and one of them
// reached it before React existed.
import { afterEach, describe, expect, it } from 'vitest';

import { safeGet, safeRemove, safeSet, safeStorage } from '@/lib/safeStorage';

const REAL = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');

function restore() {
  if (REAL) Object.defineProperty(globalThis, 'localStorage', REAL);
  else delete (globalThis as Record<string, unknown>).localStorage;
}

/** Replace `globalThis.localStorage` with *value*, or remove it when absent. */
function install(value: unknown | undefined) {
  if (value === undefined) {
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      get() {
        return undefined;
      },
    });
    return;
  }
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    writable: true,
    value,
  });
}

/** A `localStorage` whose PROPERTY ACCESS throws — the Safari/webview shape. */
function installThrowingProperty() {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    get() {
      throw new DOMException('The operation is insecure.', 'SecurityError');
    },
  });
}

afterEach(restore);

describe('safeGet', () => {
  it('reads a value when storage works', () => {
    install({ getItem: (k: string) => (k === 'a' ? 'b' : null) });
    expect(safeGet('a')).toBe('b');
  });

  it('returns null when localStorage is absent', () => {
    install(undefined);
    expect(safeGet('a')).toBeNull();
  });

  it('returns null when the property getter itself throws', () => {
    // The case a `globalThis.localStorage ?? null` outside a try would miss —
    // and the one that produced the blank screen.
    installThrowingProperty();
    expect(safeGet('a')).toBeNull();
  });

  it('returns null when getItem throws', () => {
    install({
      getItem() {
        throw new DOMException('denied', 'SecurityError');
      },
    });
    expect(safeGet('a')).toBeNull();
  });
});

describe('safeSet', () => {
  it('returns true when the write lands', () => {
    const store: Record<string, string> = {};
    install({ setItem: (k: string, v: string) => { store[k] = v; } });
    expect(safeSet('a', 'b')).toBe(true);
    expect(store.a).toBe('b');
  });

  it('returns false when setItem throws (quota exceeded)', () => {
    install({
      setItem() {
        throw new DOMException('quota', 'QuotaExceededError');
      },
    });
    expect(safeSet('a', 'b')).toBe(false);
  });

  it('returns false when storage is absent, without throwing', () => {
    install(undefined);
    expect(safeSet('a', 'b')).toBe(false);
  });
});

describe('safeRemove', () => {
  it('returns true when the erase lands', () => {
    const store: Record<string, string> = { a: 'b' };
    install({ removeItem: (k: string) => { delete store[k]; } });
    expect(safeRemove('a')).toBe(true);
    expect(store.a).toBeUndefined();
  });

  it('returns false when removeItem throws', () => {
    install({
      removeItem() {
        throw new DOMException('denied', 'SecurityError');
      },
    });
    expect(safeRemove('a')).toBe(false);
  });
});

describe('safeStorage (injected-store shape)', () => {
  it('satisfies the Storage-like contract without throwing', () => {
    installThrowingProperty();
    expect(safeStorage.getItem('a')).toBeNull();
    expect(() => safeStorage.setItem('a', 'b')).not.toThrow();
    expect(() => safeStorage.removeItem('a')).not.toThrow();
  });
});
