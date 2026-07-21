import { create } from 'zustand';

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
  document.documentElement.setAttribute('data-gem', gem);
  document.documentElement.setAttribute('data-mode', mode);
}

function storedGem(): Gem {
  const v = localStorage.getItem(GEM_KEY);
  return isGem(v) ? v : 'emerald';
}

function storedMode(): ThemeMode {
  // Light mode is infrastructure-only until pages are token-clean; anything
  // other than an explicit 'light' resolves to dark.
  return localStorage.getItem(MODE_KEY) === 'light' ? 'light' : 'dark';
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
    localStorage.setItem(GEM_KEY, gem);
    applyTheme(gem, get().mode);
    set({ gem });
  },

  setMode: (mode) => {
    localStorage.setItem(MODE_KEY, mode);
    applyTheme(get().gem, mode);
    set({ mode });
  },

  toggleMode: () => {
    const next: ThemeMode = get().mode === 'dark' ? 'light' : 'dark';
    get().setMode(next);
  },
}));

/** Apply the persisted theme before first paint. Called from main.tsx. */
export function initTheme() {
  applyTheme(storedGem(), storedMode());
}
