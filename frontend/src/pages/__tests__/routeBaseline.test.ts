/**
 * Polish Phase 6.4 — the route table and the links into it, pinned.
 *
 * Two source-level guarantees that no page test can give:
 *
 *  1. App.tsx classifies every product route the way Phases 6.1–6.3 decided:
 *     public / product / creator workspace / Writer-gated / retired /
 *     privileged / dormant. The guard on each route IS the classification.
 *
 *  2. No production file links where it should not: nothing points at the
 *     retired generator, the dormant Character Home, or a privileged tool
 *     from an ungated place. Tests are excluded; App.tsx is where the routes
 *     are declared, so it is asserted separately, not swept.
 */
import { describe, expect, it } from 'vitest';
import appSource from '../../App.tsx?raw';

const PRODUCTION = import.meta.glob(['/src/**/*.tsx', '/src/**/*.ts'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

/** Root-anchored glob keys ("/src/pages/x.tsx"), reported src-relative. */
function productionFiles(): [string, string][] {
  return Object.entries(PRODUCTION)
    .filter(([path]) => !/__tests__|\.test\.|\.d\.ts$|\/App\.tsx$|\/main\.tsx$|vite-env/.test(path))
    .map(([path, src]) => [path.replace(/^\/src\//, ''), src]);
}

/** `<Route path="X" element={<Guard` → the guard (or page) for path X. */
function elementFor(path: string): string {
  const re = new RegExp(`<Route\\s+path="${path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}"\\s+element=\\{\\s*<(\\w+)`, 's');
  const m = appSource.match(re);
  if (!m) throw new Error(`no route for ${path}`);
  return m[1];
}

describe('App route table (Phase 6 classification)', () => {
  it('privileged: 18+ Studio is AdminRoute, Admin Creator is FounderRoute', () => {
    expect(elementFor('/studio/18-plus')).toBe('AdminRoute');
    expect(elementFor('/admin-creator')).toBe('FounderRoute');
  });

  it('creator workspaces are CreatorRoute', () => {
    for (const path of ['/images', '/editor-studio', '/workspace', '/storylab', '/storylab/:storyId', '/rp-stories', '/rp-stories/:threadId']) {
      expect(elementFor(path)).toBe('CreatorRoute');
    }
  });

  it('character creation is WriterRoute — the paid unlock, not mere sign-in', () => {
    expect(elementFor('/characters/new')).toBe('WriterRoute');
  });

  it('retired: /images/new is a replace-redirect to /images and nothing else', () => {
    expect(appSource).toMatch(/<Route path="\/images\/new" element=\{<Navigate to="\/images" replace \/>\} \/>/);
    expect(appSource).not.toMatch(/ImageNew/);
  });

  it('authenticated product lives inside the ProtectedRoute + Layout shell', () => {
    const shell = appSource.slice(appSource.indexOf('<ProtectedRoute>\n              <Layout />'), appSource.indexOf('</Route>\n\n        <Route\n          path="/characters/new"'));
    for (const path of ['/', '/realms', '/realms/:realmId', '/notifications', '/spaces', '/characters', '/characters/:id', '/scenes/:sceneId', '/profile', '/become-a-writer']) {
      expect(shell).toContain(`path="${path}"`);
    }
  });

  it('messaging routes are ProtectedRoute (sign-in, no creator gate)', () => {
    for (const path of ['/messages', '/messages/new', '/messages/:id']) {
      expect(elementFor(path)).toBe('ProtectedRoute');
    }
  });

  it('auth routes are PublicOnlyRoute', () => {
    for (const path of ['/login', '/register', '/forgot-password', '/reset-password']) {
      expect(elementFor(path)).toBe('PublicOnlyRoute');
    }
  });

  it('dormant: /c/:id is declared outside every guard and shell, unchanged', () => {
    expect(elementFor('/c/:id')).toBe('CharacterHome');
    const idx = appSource.indexOf('path="/c/:id"');
    const shellIdx = appSource.indexOf('<ProtectedRoute>\n              <Layout />');
    expect(idx).toBeGreaterThan(0);
    expect(idx).toBeLessThan(shellIdx);
  });

  it('legacy /u/* profile links land on the feed', () => {
    expect(appSource).toMatch(/<Route path="\/u\/\*" element=\{<Navigate to="\/" replace \/>\} \/>/);
  });
});

describe('production links (every non-test source file)', () => {
  const files = productionFiles();

  it('sweeps a real corpus', () => {
    expect(files.length).toBeGreaterThan(100);
    expect(files.some(([p]) => p.endsWith('/Layout.tsx'))).toBe(true);
  });

  it('nothing links to the retired generator or its retired endpoint', () => {
    for (const [path, src] of files) {
      expect(src, path).not.toMatch(/['"`]\/images\/new/);
      expect(src, path).not.toMatch(/['"`]\/images\/generate/);
    }
  });

  it('nothing links to the dormant Character Home', () => {
    for (const [path, src] of files) {
      expect(src, path).not.toMatch(/(to=|navigate\(|href=)\s*['"`{]*\/c\//);
    }
  });

  it('Quick Create and FakeAI are gone from product code', () => {
    for (const [path, src] of files) {
      const code = src.split('\n').filter((l) => !l.trim().startsWith('//') && !l.trim().startsWith('*')).join('\n');
      expect(code, path).not.toMatch(/quick create|quickcreate|fakeai|fake_ai/i);
    }
  });

  it('privileged tools are linked only from their gated doors', () => {
    const studioLinkers = files.filter(([, s]) => /\/studio\/18-plus/.test(s)).map(([p]) => p);
    const adminCreatorLinkers = files.filter(([, s]) => /\/admin-creator/.test(s)).map(([p]) => p);
    expect(studioLinkers.sort()).toEqual(['features/images/components/SceneGeneratorPanel.tsx', 'pages/Images.tsx']);
    expect(adminCreatorLinkers.sort()).toEqual(['pages/Images.tsx']);
  });

  it('Realm Scenes are reached only from RealmDetail (founder-gated section)', () => {
    const linkers = files.filter(([, s]) => /(to=|navigate\()\s*['"`{]*\/scenes\//.test(s)).map(([p]) => p);
    expect(linkers).toEqual(['pages/RealmDetail.tsx']);
  });
});
