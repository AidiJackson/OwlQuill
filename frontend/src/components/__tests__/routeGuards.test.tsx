// @vitest-environment jsdom
//
// The only DOM-environment suite in the project. The redirect race and the
// deep-link round trip are decisions a component makes across renders as the
// auth status changes, so they cannot be reached by testing pure functions:
// the bug being fixed here is *when* a redirect fires, not what it computes.
// The docblock above opts this one file into jsdom; the suite-wide default in
// vitest.config.ts stays `node` and every other test still runs there.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import { useAuthStore } from '@/lib/store';
import type { User } from '@/lib/types';
import {
  CreatorRoute,
  ProtectedRoute,
  PublicOnlyRoute,
  WriterRoute,
} from '@/components/routeGuards';

// The entitlement fallbacks are real pages that fetch on mount; they are not
// what these tests are about, so they stand in as markers.
vi.mock('@/components/WandererNotice', () => ({
  default: () => <div>WANDERER NOTICE</div>,
}));
vi.mock('@/pages/BecomeAWriter', () => ({
  default: () => <div>BECOME A WRITER</div>,
}));

function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: 1,
    email: 'a@e.com',
    username: 'a',
    created_at: '',
    updated_at: '',
    ...overrides,
  } as User;
}

/** Renders the current location so a test can assert where it ended up. */
function LocationProbe() {
  const location = useLocation();
  const state = location.state as { from?: unknown } | null;
  return (
    <div>
      <span data-testid="path">
        {location.pathname}
        {location.search}
        {location.hash}
      </span>
      <span data-testid="from">{typeof state?.from === 'string' ? state.from : ''}</span>
    </div>
  );
}

function Secret() {
  return <div>SECRET</div>;
}

/**
 * The app's real shape at the routes under test: a protected deep link, the
 * login page it redirects to, and the feed it falls back to.
 */
function renderApp(initialEntry: string, protectedElement: React.ReactNode = <Secret />) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route
          path="/login"
          element={
            <PublicOnlyRoute>
              <div>
                LOGIN PAGE
                <LocationProbe />
              </div>
            </PublicOnlyRoute>
          }
        />
        <Route
          path="/"
          element={
            <div>
              FEED
              <LocationProbe />
            </div>
          }
        />
        <Route
          path="/characters/:id"
          element={
            <ProtectedRoute>
              <div>
                {protectedElement}
                <LocationProbe />
              </div>
            </ProtectedRoute>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

const path = () => screen.getByTestId('path').textContent;

beforeEach(() => {
  useAuthStore.setState({ user: null, status: 'unauthenticated', isLoading: false });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// ── The race: no redirect before /me resolves ────────────────────────────────

describe('ProtectedRoute during auth resolution', () => {
  it('does not redirect a persisted session to /login before /me resolves', () => {
    useAuthStore.setState({ status: 'resolving', user: null });
    renderApp('/characters/59');

    // Neither the destination nor the login page — a placeholder, and the URL
    // is untouched, so the deep link is still live when resolution lands.
    expect(screen.queryByText('LOGIN PAGE')).toBeNull();
    expect(screen.queryByText('SECRET')).toBeNull();
    expect(screen.getByRole('status')).toBeTruthy();
  });

  it('shows the destination once resolution says authenticated', () => {
    useAuthStore.setState({ status: 'resolving', user: null });
    renderApp('/characters/59?tab=media');

    act(() => {
      useAuthStore.setState({ status: 'authenticated', user: makeUser() });
    });

    expect(screen.getByText('SECRET')).toBeTruthy();
    expect(path()).toBe('/characters/59?tab=media');
  });

  it('redirects only after resolution says unauthenticated', () => {
    useAuthStore.setState({ status: 'resolving', user: null });
    renderApp('/characters/59');
    expect(screen.queryByText('LOGIN PAGE')).toBeNull();

    act(() => {
      useAuthStore.setState({ status: 'unauthenticated', user: null });
    });

    expect(screen.getByText('LOGIN PAGE')).toBeTruthy();
    expect(path()).toBe('/login');
  });

  it('redirects immediately when there was never a token to resolve', () => {
    // No token means nothing to check, so an anonymous visitor never waits.
    useAuthStore.setState({ status: 'unauthenticated', user: null });
    renderApp('/characters/59');

    expect(screen.getByText('LOGIN PAGE')).toBeTruthy();
  });

  it('treats an expired token as logged out and redirects normally', () => {
    // The lifecycle of an invalid token: resolving, /me refuses, unauthenticated.
    useAuthStore.setState({ status: 'resolving', user: null });
    renderApp('/characters/59');

    act(() => {
      // What fetchUser's catch branch does.
      useAuthStore.setState({ user: null, status: 'unauthenticated', isLoading: false });
    });

    expect(screen.getByText('LOGIN PAGE')).toBeTruthy();
    expect(screen.getByTestId('from').textContent).toBe('/characters/59');
  });
});

// ── The destination survives the round trip ──────────────────────────────────

describe('ProtectedRoute preserves the intended destination', () => {
  it('records the pathname', () => {
    renderApp('/characters/59');
    expect(screen.getByTestId('from').textContent).toBe('/characters/59');
  });

  it('records search parameters', () => {
    renderApp('/characters/59?tab=media');
    expect(screen.getByTestId('from').textContent).toBe('/characters/59?tab=media');
  });

  it('records the hash', () => {
    renderApp('/characters/59#foo');
    expect(screen.getByTestId('from').textContent).toBe('/characters/59#foo');
  });

  it('records pathname, search and hash together', () => {
    renderApp('/characters/59?tab=media#foo');
    expect(screen.getByTestId('from').textContent).toBe('/characters/59?tab=media#foo');
  });

  it('replaces rather than stacks, so back does not return to the dead link', () => {
    renderApp('/characters/59');
    expect(screen.getByText('LOGIN PAGE')).toBeTruthy();
    expect(path()).toBe('/login');
  });
});

// ── /login for someone already signed in ─────────────────────────────────────

describe('PublicOnlyRoute', () => {
  it('waits for resolution instead of bouncing a session that is still loading', () => {
    useAuthStore.setState({ status: 'resolving', user: null });
    renderApp('/login');

    expect(screen.queryByText('LOGIN PAGE')).toBeNull();
    expect(screen.queryByText('FEED')).toBeNull();
    expect(screen.getByRole('status')).toBeTruthy();
  });

  it('sends an authenticated visitor with no return destination to the feed', () => {
    useAuthStore.setState({ status: 'authenticated', user: makeUser() });
    renderApp('/login');

    expect(screen.getByText('FEED')).toBeTruthy();
    expect(path()).toBe('/');
  });

  it('shows the form to an unauthenticated visitor', () => {
    renderApp('/login');
    expect(screen.getByText('LOGIN PAGE')).toBeTruthy();
  });

  it('honours a safe return destination for an already-authenticated visitor', () => {
    // A deep link opened while a session is live in another tab: the redirect
    // records the destination, resolution completes as authenticated, and they
    // land on the link rather than the feed.
    useAuthStore.setState({ status: 'resolving', user: null });
    renderApp('/characters/59?tab=media');

    act(() => {
      useAuthStore.setState({ status: 'unauthenticated', user: null });
    });
    expect(screen.getByText('LOGIN PAGE')).toBeTruthy();

    act(() => {
      useAuthStore.setState({ status: 'authenticated', user: makeUser() });
    });
    expect(path()).toBe('/characters/59?tab=media');
  });

  it('does not loop when the recorded destination is /login itself', () => {
    useAuthStore.setState({ status: 'authenticated', user: makeUser() });
    render(
      <MemoryRouter initialEntries={[{ pathname: '/login', state: { from: '/login' } }]}>
        <Routes>
          <Route
            path="/login"
            element={
              <PublicOnlyRoute>
                <div>LOGIN PAGE</div>
              </PublicOnlyRoute>
            }
          />
          <Route path="/" element={<div>FEED<LocationProbe /></div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByText('FEED')).toBeTruthy();
    expect(path()).toBe('/');
  });

  it('refuses an external return destination', () => {
    useAuthStore.setState({ status: 'authenticated', user: makeUser() });
    for (const hostile of ['https://evil.example', '//evil.example', '/\\evil.example']) {
      render(
        <MemoryRouter initialEntries={[{ pathname: '/login', state: { from: hostile } }]}>
          <Routes>
            <Route
              path="/login"
              element={
                <PublicOnlyRoute>
                  <div>LOGIN PAGE</div>
                </PublicOnlyRoute>
              }
            />
            <Route path="/" element={<div>FEED<LocationProbe /></div>} />
          </Routes>
        </MemoryRouter>
      );
      expect(screen.getByText('FEED')).toBeTruthy();
      expect(screen.getByTestId('path').textContent).toBe('/');
      cleanup();
    }
  });
});

// ── Entitlement routes inherit the fix rather than re-deciding ───────────────

describe('CreatorRoute and WriterRoute wait for auth resolution', () => {
  function renderGuard(guard: React.ReactNode, entry = '/characters/59') {
    return render(
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route
            path="/login"
            element={
              <div>
                LOGIN PAGE
                <LocationProbe />
              </div>
            }
          />
          <Route path="/characters/:id" element={guard} />
        </Routes>
      </MemoryRouter>
    );
  }

  it('CreatorRoute shows neither the workspace nor the Wanderer notice while resolving', () => {
    useAuthStore.setState({ status: 'resolving', user: null });
    renderGuard(
      <CreatorRoute workspaceName="W" description="d">
        <Secret />
      </CreatorRoute>
    );

    expect(screen.queryByText('SECRET')).toBeNull();
    expect(screen.queryByText('WANDERER NOTICE')).toBeNull();
    expect(screen.queryByText('LOGIN PAGE')).toBeNull();
    expect(screen.getByRole('status')).toBeTruthy();
  });

  it('CreatorRoute applies the entitlement only once the user has landed', () => {
    useAuthStore.setState({ status: 'resolving', user: null });
    renderGuard(
      <CreatorRoute workspaceName="W" description="d">
        <Secret />
      </CreatorRoute>
    );

    act(() => {
      useAuthStore.setState({ status: 'authenticated', user: makeUser({ character_count: 0 }) });
    });
    expect(screen.getByText('WANDERER NOTICE')).toBeTruthy();
  });

  it('CreatorRoute admits a creator', () => {
    useAuthStore.setState({ status: 'authenticated', user: makeUser({ character_count: 1 }) });
    renderGuard(
      <CreatorRoute workspaceName="W" description="d">
        <Secret />
      </CreatorRoute>
    );
    expect(screen.getByText('SECRET')).toBeTruthy();
  });

  it('CreatorRoute preserves the destination when it does redirect', () => {
    renderGuard(
      <CreatorRoute workspaceName="W" description="d">
        <Secret />
      </CreatorRoute>,
      '/characters/59?tab=media'
    );
    expect(screen.getByText('LOGIN PAGE')).toBeTruthy();
    expect(screen.getByTestId('from').textContent).toBe('/characters/59?tab=media');
  });

  it('WriterRoute shows neither the flow nor the paywall while resolving', () => {
    useAuthStore.setState({ status: 'resolving', user: null });
    renderGuard(
      <WriterRoute>
        <Secret />
      </WriterRoute>
    );

    expect(screen.queryByText('SECRET')).toBeNull();
    expect(screen.queryByText('BECOME A WRITER')).toBeNull();
    expect(screen.queryByText('LOGIN PAGE')).toBeNull();
    expect(screen.getByRole('status')).toBeTruthy();
  });

  it('WriterRoute applies the entitlement only once the user has landed', () => {
    useAuthStore.setState({ status: 'resolving', user: null });
    renderGuard(
      <WriterRoute>
        <Secret />
      </WriterRoute>
    );

    act(() => {
      useAuthStore.setState({
        status: 'authenticated',
        user: makeUser({ can_create_character: false }),
      });
    });
    expect(screen.getByText('BECOME A WRITER')).toBeTruthy();
  });

  it('WriterRoute admits a Writer', () => {
    useAuthStore.setState({
      status: 'authenticated',
      user: makeUser({ can_create_character: true }),
    });
    renderGuard(
      <WriterRoute>
        <Secret />
      </WriterRoute>
    );
    expect(screen.getByText('SECRET')).toBeTruthy();
  });
});

// ── Logout ───────────────────────────────────────────────────────────────────

describe('logout', () => {
  it('leaves auth resolved, so the next protected route redirects instead of hanging', () => {
    localStorage.setItem('token', 'stale');
    useAuthStore.setState({ status: 'authenticated', user: makeUser() });

    act(() => {
      useAuthStore.getState().logout();
    });

    expect(useAuthStore.getState().status).toBe('unauthenticated');
    expect(useAuthStore.getState().user).toBeNull();
    expect(localStorage.getItem('token')).toBeNull();

    renderApp('/characters/59');
    expect(screen.getByText('LOGIN PAGE')).toBeTruthy();
  });

  it('leaves no return destination behind from the session that ended', () => {
    // Layout navigates to /login after logout with no state, so a stale
    // destination from an earlier redirect cannot resurface and bounce the
    // next visitor somewhere they did not ask for.
    useAuthStore.setState({ status: 'authenticated', user: makeUser() });
    act(() => {
      useAuthStore.getState().logout();
    });

    render(
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route
            path="/login"
            element={
              <PublicOnlyRoute>
                <div>
                  LOGIN PAGE
                  <LocationProbe />
                </div>
              </PublicOnlyRoute>
            }
          />
          <Route path="/" element={<div>FEED</div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByText('LOGIN PAGE')).toBeTruthy();
    expect(screen.getByTestId('from').textContent).toBe('');
  });
});
