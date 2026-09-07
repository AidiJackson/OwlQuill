// What Ficshon does when the browser refuses site storage.
//
// THE REGRESSION THIS PINS. Three modules used to read `localStorage` during
// MODULE EVALUATION — the auth store's zustand initializer (through
// `apiClient.hasToken()`), the theme store's initializer, and `initTheme()` in
// main.tsx. Zustand builds initial state eagerly, so importing either store was
// enough to throw, and a throw there aborts module evaluation before
// `createRoot().render()`. React never mounted, no error boundary could catch
// it — a boundary is a component and there was no tree to hold one — and the
// visitor got a permanent white page on every route, including /login and the
// public Character Home, neither of which needs storage at all.
//
// Every test installs the throwing storage BEFORE a fresh dynamic import, which
// is the only way to reproduce a module-evaluation failure. `vi.resetModules()`
// between cases keeps the stores from being shared.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const REAL = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');

/** `localStorage` whose property access throws — Safari private / webviews. */
function denyStorage() {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    get() {
      throw new DOMException('The operation is insecure.', 'SecurityError');
    },
  });
}

/** Storage that reads fine but refuses every write — quota exhausted. */
function readOnlyStorage(seed: Record<string, string> = {}) {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    writable: true,
    value: {
      getItem: (k: string) => (k in seed ? seed[k] : null),
      setItem() {
        throw new DOMException('quota', 'QuotaExceededError');
      },
      removeItem() {
        throw new DOMException('denied', 'SecurityError');
      },
    },
  });
}

function installDocument() {
  const attrs: Record<string, string> = {};
  (globalThis as Record<string, unknown>).document = {
    documentElement: {
      setAttribute: (k: string, v: string) => {
        attrs[k] = v;
      },
    },
  };
  return attrs;
}

afterEach(() => {
  if (REAL) Object.defineProperty(globalThis, 'localStorage', REAL);
  else delete (globalThis as Record<string, unknown>).localStorage;
  delete (globalThis as Record<string, unknown>).document;
  vi.resetModules();
});

beforeEach(() => {
  vi.resetModules();
});

// ── Theme ────────────────────────────────────────────────────────────────────

describe('theme under denied storage', () => {
  it('imports without throwing — the module-evaluation crash path', async () => {
    denyStorage();
    installDocument();
    await expect(import('@/lib/theme')).resolves.toBeDefined();
  });

  it('opens at the documented defaults', async () => {
    denyStorage();
    installDocument();
    const { useThemeStore } = await import('@/lib/theme');
    expect(useThemeStore.getState().gem).toBe('emerald');
    expect(useThemeStore.getState().mode).toBe('dark');
  });

  it('initTheme does not throw and still paints the defaults', async () => {
    denyStorage();
    const attrs = installDocument();
    const { initTheme } = await import('@/lib/theme');
    expect(() => initTheme()).not.toThrow();
    expect(attrs['data-gem']).toBe('emerald');
    expect(attrs['data-mode']).toBe('dark');
  });

  it('initTheme does not throw when there is no document either', async () => {
    // The pre-mount contract does not depend on a DOM being present: whatever
    // fails, main.tsx must still reach createRoot().
    denyStorage();
    const { initTheme } = await import('@/lib/theme');
    expect(() => initTheme()).not.toThrow();
  });

  it('a theme change still applies for this session when the write is refused', async () => {
    readOnlyStorage();
    const attrs = installDocument();
    const { useThemeStore } = await import('@/lib/theme');
    useThemeStore.getState().setMode('light');
    expect(useThemeStore.getState().mode).toBe('light');
    expect(attrs['data-mode']).toBe('light');
  });
});

// ── Auth ─────────────────────────────────────────────────────────────────────

describe('auth under denied storage', () => {
  it('the auth store imports without throwing', async () => {
    // The EARLIEST of the three crash paths: App.tsx imports the store on its
    // third line, long before theme is reached.
    denyStorage();
    await expect(import('@/lib/store')).resolves.toBeDefined();
  });

  it('opens unauthenticated — a read failure means no token', async () => {
    denyStorage();
    const { useAuthStore } = await import('@/lib/store');
    expect(useAuthStore.getState().status).toBe('unauthenticated');
    expect(useAuthStore.getState().user).toBeNull();
  });

  it('hasToken reports false rather than throwing', async () => {
    denyStorage();
    const { apiClient } = await import('@/lib/apiClient');
    expect(apiClient.hasToken()).toBe(false);
  });

  it('logout still resolves auth state when removeItem throws', async () => {
    // Previously fatal to the flow: `apiClient.logout()` threw before the store
    // reached its `set(...)`, so the UI stayed signed in AND the token stayed
    // on disk. The erase may still fail; what must not fail is the decision.
    readOnlyStorage({ token: 'stale' });
    const { useAuthStore } = await import('@/lib/store');
    useAuthStore.setState({ status: 'authenticated', user: { id: 1 } as never });

    expect(() => useAuthStore.getState().logout()).not.toThrow();
    expect(useAuthStore.getState().status).toBe('unauthenticated');
    expect(useAuthStore.getState().user).toBeNull();
  });

  it('login fails honestly when the token cannot be persisted', async () => {
    // Not a crash, and not a silent half-success either. Every authenticated
    // request reads the token back, so a session whose token was never stored
    // would look signed in and 401 on everything; the user is told the real
    // cause instead.
    readOnlyStorage();
    const { apiClient } = await import('@/lib/apiClient');
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ access_token: 'jwt', token_type: 'bearer' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiClient.login('a@e.com', 'pw')).rejects.toThrow(/site storage/i);
    vi.unstubAllGlobals();
  });
});
