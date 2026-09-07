// Browser storage as OPTIONAL infrastructure.
//
// THE INVARIANT: a denied or throwing `localStorage` degrades persistence. It
// never crashes Ficshon.
//
// WHY THIS EXISTS. Before this, three separate paths read `localStorage`
// directly during module evaluation — the auth store's zustand initializer (via
// `apiClient.hasToken()`), the theme store's initializer, and `initTheme()` in
// main.tsx. Zustand builds initial state eagerly, so merely IMPORTING either
// store was enough to throw. A throw there aborts module evaluation before
// `createRoot().render()` ever runs, which means React never mounts, no error
// boundary can exist to catch it (a boundary is a component; there is no tree
// to put it in), and the visitor gets a permanent white page on every route —
// including `/login` and the public Character Home, neither of which needs
// storage at all.
//
// That is not a hypothetical. `localStorage` throws in ordinary conditions:
// Safari private browsing, embedded webviews with site data blocked, enterprise
// browser policy, and any profile where cookies/site-data are denied. In some
// of those the PROPERTY ACCESS itself throws, before any method is called,
// which is why `storage()` below wraps the lookup and not just the call.
//
// SEMANTICS, chosen so callers rarely need to branch:
//
//   safeGet    -> `null` on any failure. Indistinguishable from "not stored",
//                 which is the correct meaning for every key in this app: no
//                 token means signed out, no theme means the default, no draft
//                 means an empty draft. Callers already handle `null`.
//   safeSet    -> `false` on any failure. Returned rather than swallowed
//                 silently so a caller that genuinely needs to know (login,
//                 which cannot hold a session without it) can say something
//                 honest instead of pretending it worked.
//   safeRemove -> `false` on any failure. A failed erase must never stop the
//                 caller doing the rest of its job — logout in particular
//                 clears in-memory auth state whatever storage does.
//
// Deliberately three functions and no class. There is no state to hold and no
// lifecycle to manage; an abstraction with instances would be ceremony around
// a try/catch. `features/adminCreator/draftStorage.ts` already solves the same
// problem for `sessionStorage` with an injected store, and stays as it is —
// this is the counterpart for the direct-`localStorage` callers, not a
// replacement for a working design.

/**
 * `localStorage` if it is present AND reachable, otherwise `null`.
 *
 * The lookup is inside the `try` on purpose: reading the property can itself
 * throw in a webview with site data blocked, so `globalThis.localStorage ??
 * null` outside a guard would be exactly the crash this module exists to
 * prevent.
 */
function storage(): Storage | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

/** The stored value for *key*, or `null` when storage is unavailable. */
export function safeGet(key: string): string | null {
  const store = storage();
  if (!store) return null;
  try {
    return store.getItem(key);
  } catch {
    return null;
  }
}

/** Persist *value*; `false` when storage refused it (denied, or quota full). */
export function safeSet(key: string, value: string): boolean {
  const store = storage();
  if (!store) return false;
  try {
    store.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

/** Erase *key*; `false` when storage refused. Callers proceed regardless. */
export function safeRemove(key: string): boolean {
  const store = storage();
  if (!store) return false;
  try {
    store.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

/**
 * A `Storage`-shaped object backed by the safe functions above.
 *
 * For the handful of helpers that already take an injected store — the Editor
 * Studio provider preference is the live example — so they keep their
 * dependency injection (and their tests keep passing a fake) while the real
 * call site stops handing them the raw, throwing `localStorage`.
 *
 * Only the three methods those callers use are implemented. It is not a
 * `Storage` polyfill and does not pretend to be one.
 */
export const safeStorage = {
  getItem: safeGet,
  setItem: (key: string, value: string): void => {
    safeSet(key, value);
  },
  removeItem: (key: string): void => {
    safeRemove(key);
  },
};
