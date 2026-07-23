import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * Theme regression coverage. Light mode is now a supported product theme, so:
 *  - dark is the default when nothing is persisted,
 *  - an explicit persisted 'light' is honoured (a returning user keeps light),
 *  - applyTheme reflects both gem + mode onto the document element,
 *  - toggling flips and persists the mode.
 *
 * theme.ts reads localStorage / document at module-eval time (store creation),
 * so the globals are stubbed BEFORE a fresh dynamic import in each case.
 */

function installGlobals(seed: Record<string, string> = {}) {
  const store: Record<string, string> = { ...seed };
  const attrs: Record<string, string> = {};
  (globalThis as any).localStorage = {
    getItem: (k: string) => (k in store ? store[k] : null),
    setItem: (k: string, v: string) => { store[k] = String(v); },
    removeItem: (k: string) => { delete store[k]; },
  };
  (globalThis as any).document = {
    documentElement: { setAttribute: (k: string, v: string) => { attrs[k] = v; } },
  };
  return { store, attrs };
}

async function freshTheme() {
  vi.resetModules();
  return import('../theme');
}

describe('theme mode persistence', () => {
  beforeEach(() => { vi.resetModules(); });

  it('defaults to dark when nothing is persisted', async () => {
    installGlobals();
    const { useThemeStore } = await freshTheme();
    expect(useThemeStore.getState().mode).toBe('dark');
  });

  it('honours a persisted light preference for a returning user', async () => {
    installGlobals({ 'ficshon.theme.mode': 'light' });
    const { useThemeStore } = await freshTheme();
    expect(useThemeStore.getState().mode).toBe('light');
  });

  it('coerces any unknown persisted value to dark (never a broken state)', async () => {
    installGlobals({ 'ficshon.theme.mode': 'sepia' });
    const { useThemeStore } = await freshTheme();
    expect(useThemeStore.getState().mode).toBe('dark');
  });

  it('applyTheme reflects gem + mode onto the document element', async () => {
    const { attrs } = installGlobals({ 'ficshon.theme.gem': 'sapphire', 'ficshon.theme.mode': 'light' });
    const { initTheme } = await freshTheme();
    initTheme();
    expect(attrs['data-mode']).toBe('light');
    expect(attrs['data-gem']).toBe('sapphire');
  });

  it('toggleMode flips dark -> light and persists it', async () => {
    const { store, attrs } = installGlobals();
    const { useThemeStore } = await freshTheme();
    useThemeStore.getState().toggleMode();
    expect(useThemeStore.getState().mode).toBe('light');
    expect(store['ficshon.theme.mode']).toBe('light');
    expect(attrs['data-mode']).toBe('light');
  });
});
