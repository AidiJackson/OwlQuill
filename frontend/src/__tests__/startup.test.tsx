// @vitest-environment jsdom
//
// THE regression pin for the blank-screen class: a denied `localStorage` must
// not stop `createRoot().render()`.
//
// This imports the real `main.tsx`, so it exercises the actual boot sequence —
// the import graph (which evaluates the auth store and the theme store, both of
// which used to read storage during module evaluation), the `initTheme()` call,
// the root-element lookup, and the render. Only `App` is stood in for: the real
// one mounts thirty-odd pages that fetch on mount, and none of that is what
// this test is about. Everything upstream of the render — which is where the
// failure lived — is the genuine article.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../App.tsx', () => ({
  default: () => 'FICSHON MOUNTED',
}));

const REAL = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');

function denyStorage() {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    get() {
      throw new DOMException('The operation is insecure.', 'SecurityError');
    },
  });
}

beforeEach(() => {
  vi.resetModules();
  document.body.innerHTML = '<div id="root"></div>';
});

afterEach(() => {
  if (REAL) Object.defineProperty(globalThis, 'localStorage', REAL);
  else delete (globalThis as Record<string, unknown>).localStorage;
  document.body.innerHTML = '';
  vi.resetModules();
});

describe('startup with denied localStorage', () => {
  it('still mounts React into #root', async () => {
    denyStorage();

    await import('../main.tsx');
    // React 18 renders through a scheduler callback, so yield once before
    // asserting rather than assuming the render is synchronous.
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById('root')?.textContent).toContain('FICSHON MOUNTED');
  });

  it('does not throw out of module evaluation', async () => {
    denyStorage();
    await expect(import('../main.tsx')).resolves.toBeDefined();
  });

  it('mounts normally when storage works, and applies the theme', async () => {
    // The other half: hardening must not have broken the ordinary path.
    await import('../main.tsx');
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById('root')?.textContent).toContain('FICSHON MOUNTED');
    expect(document.documentElement.getAttribute('data-gem')).toBe('emerald');
    expect(document.documentElement.getAttribute('data-mode')).toBe('dark');
  });

  it('logs rather than throwing when #root is missing', async () => {
    // The `!` non-null assertion used to compile away to `createRoot(null)`,
    // which throws about the React API instead of about the missing element.
    document.body.innerHTML = '';
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});

    await expect(import('../main.tsx')).resolves.toBeDefined();
    expect(spy).toHaveBeenCalledWith(expect.stringContaining('#root'));

    spy.mockRestore();
  });
});
