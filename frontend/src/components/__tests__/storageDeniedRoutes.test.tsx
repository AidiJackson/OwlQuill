// @vitest-environment jsdom
//
// Route-level half of the storage hardening: a denied `localStorage` must not
// crash a page merely because a PREFERENCE could not be read or written.
//
// Four representatives rather than all seven migrated files, chosen for what
// each proves:
//
//   Layout    — the only one whose failure was app-wide rather than route-local.
//               It wraps every authenticated page, so its `messages_seen` read
//               (a `useState` initializer) and its write (an effect) meant a
//               denied browser blanked the entire signed-in product.
//   Home      — a `useState` initializer AND a removal in an effect.
//   Workspace — the heaviest persistence surface: six reads at first render and
//               a batch of writes in effects (WriteSpace autosave).
//   StoryLab  — a `useState` initializer that WRITES on the read path (it mints
//               and stores a story id when none exists), the one shape where a
//               refused write happens during render.
//
// Every network call is stubbed. These assert one thing each: the component
// renders under storage denial. What it renders is other suites' business.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { useAuthStore } from '@/lib/store';
import type { User } from '@/lib/types';

vi.mock('@/lib/apiClient', () => {
  const resolved = () => Promise.resolve([]);
  return {
    apiClient: new Proxy(
      {},
      {
        get: (_t, prop) => {
          if (prop === 'hasToken') return () => false;
          return resolved;
        },
      },
    ),
  };
});

const REAL = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');

/** Storage that throws on property access — Safari private / blocked webview. */
function denyStorage() {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    get() {
      throw new DOMException('The operation is insecure.', 'SecurityError');
    },
  });
}

function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: 1,
    email: 'a@e.com',
    username: 'a',
    character_count: 1,
    created_at: '',
    updated_at: '',
    ...overrides,
  } as User;
}

beforeEach(() => {
  denyStorage();
  useAuthStore.setState({ status: 'authenticated', user: makeUser() });
});

afterEach(() => {
  cleanup();
  if (REAL) Object.defineProperty(globalThis, 'localStorage', REAL);
  else delete (globalThis as Record<string, unknown>).localStorage;
  vi.restoreAllMocks();
});

async function renderRoute(importer: () => Promise<{ default: React.ComponentType }>) {
  const { default: Component } = await importer();
  return render(
    <MemoryRouter>
      <Component />
    </MemoryRouter>,
  );
}

describe('routes under denied localStorage', () => {
  it('Layout renders — the app-wide case', async () => {
    // Its `messages_seen` read runs in a useState initializer and its write in
    // an effect, so before the hardening a denied browser blanked every
    // authenticated page in the product, not one route.
    const { container } = await renderRoute(() => import('@/components/Layout'));
    expect(container.textContent).toBeTruthy();
  });

  it('Home renders', async () => {
    const { container } = await renderRoute(() => import('@/pages/Home'));
    expect(container).toBeTruthy();
  });

  it('Workspace renders — six reads at first render plus autosave writes', async () => {
    const { container } = await renderRoute(() => import('@/pages/Workspace'));
    expect(container).toBeTruthy();
  });

  it('StoryLab renders — the read path that also writes', async () => {
    const { container } = await renderRoute(() => import('@/pages/StoryLab'));
    expect(container).toBeTruthy();
  });
});
