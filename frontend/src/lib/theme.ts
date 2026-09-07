import { create } from 'zustand';

import { safeGet, safeSet } from './safeStorage';

/** Gemstone accent themes (UI v2). Emerald is the default — it matches the
 *  existing brand accent so unmigrated pages stay coherent. */
export type Gem = 'emerald' | 'sapphire' | 'amethyst' | 'ruby' | 'gold' | 'obsidian';
export type ThemeMode = 'dark' | 'light';

export const GEMS: { id: Gem; label: string; color: string }[] = [
  { id: 'emerald',  label: 'Emerald',  color: '#2dc896' },
  { id: 'sapphire', label: 'Sapphire', color: '#4f8ef7' },
  { id: 'amethyst', label: 'Amethyst', color: '#9b6ef2' },
  { id: 'ruby',     label: 'Ruby',     color: '#e05570' },
  { id: 'gold',     label: 'Gold',     color: '#cc9f44' },
  { id: 'obsidian', label: 'Obsidian', color: '#b0b8c8' },
];

const GEM_KEY = 'ficshon.theme.gem';
const MODE_KEY = 'ficshon.theme.mode';

const isGem = (v: unknown): v is Gem => GEMS.some((g) => g.id === v);

function applyTheme(gem: Gem, mode: ThemeMode) {
  // Guarded because this runs BEFORE React mounts (see `initTheme`). Painting
  // the theme is a presentation nicety; failing to paint it must never be the
  // reason the application does not start. In a browser this cannot throw —
  // the guard is for the pre-mount contract, and for non-DOM environments.
  try {
    document.documentElement.setAttribute('data-gem', gem);
    document.documentElement.setAttribute('data-mode', mode);
  } catch {
    /* no document to paint — the app still mounts and renders at defaults */
  }
}

function storedGem(): Gem {
  // `safeGet` returns null when storage is denied, which `isGem` rejects, so
  // "storage refused" and "nothing stored" land on the same default. That is
  // the honest answer: no stored preference means the default preference.
  const v = safeGet(GEM_KEY);
  return isGem(v) ? v : 'emerald';
}

function storedMode(): ThemeMode {
  // Light mode is a supported product theme. Dark remains the default when no
  // explicit preference is stored; an explicit 'light' is honoured.
  return safeGet(MODE_KEY) === 'light' ? 'light' : 'dark';
}

interface ThemeState {
  gem: Gem;
  mode: ThemeMode;
  setGem: (gem: Gem) => void;
  setMode: (mode: ThemeMode) => void;
  toggleMode: () => void;
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  gem: storedGem(),
  mode: storedMode(),

  setGem: (gem) => {
    // A refused write loses the preference on reload, nothing more: the theme
    // still applies for this session because `applyTheme` and `set` follow.
    safeSet(GEM_KEY, gem);
    applyTheme(gem, get().mode);
    set({ gem });
  },

  setMode: (mode) => {
    safeSet(MODE_KEY, mode);
    applyTheme(get().gem, mode);
    set({ mode });
  },

  toggleMode: () => {
    const next: ThemeMode = get().mode === 'dark' ? 'light' : 'dark';
    get().setMode(next);
  },
}));

/**
 * Apply the persisted theme before first paint. Called from main.tsx.
 *
 * CANNOT THROW, and that is the point rather than a detail. This runs before
 * `createRoot().render()`, so a throw here aborts module evaluation, React
 * never mounts, and no error boundary can catch it — a boundary is a component
 * and there would be no tree to hold one. Every part is now non-throwing on
 * its own (`safeGet` for the reads, a guard inside `applyTheme` for the DOM),
 * so the caller in main.tsx needs no special handling for the normal case.
 */
export function initTheme() {
  applyTheme(storedGem(), storedMode());
}
