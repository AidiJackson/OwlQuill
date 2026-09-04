// @vitest-environment jsdom
//
// A DOM suite because what is being defended is what the page RENDERS for a
// stranger — which sections appear, which never do — and that is not reachable
// from pure functions. The suite-wide default in vitest.config.ts stays `node`.
/**
 * The public Character Home.
 *
 * What these tests are really defending is that this page cannot become an app
 * page. Two failure modes matter more than the rest:
 *
 * 1. **Owner chrome leaking onto a public surface.** Nothing here may render
 *    Manage, Message, Mentions, a Stories placeholder, a cover picker or a
 *    post/image count. Asserted by absence, by name, so a future refactor that
 *    reuses a piece of the authenticated page fails loudly.
 * 2. **Emptiness being announced instead of omitted.** The authenticated page
 *    says "No Posts Yet" — correct guidance for an owner, and precisely wrong
 *    on a stranger's first impression. A young Home must read as new, never as
 *    unfinished.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  CharacterHomePublic,
  CharacterHomePostPublic,
  CharacterImagePublic,
} from '@/lib/types';

const getPublicCharacterHome = vi.fn();
const getPublicCharacterHomePosts = vi.fn();
const getPublicCharacterHomeImages = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    getPublicCharacterHome: (...a: unknown[]) => getPublicCharacterHome(...a),
    getPublicCharacterHomePosts: (...a: unknown[]) => getPublicCharacterHomePosts(...a),
    getPublicCharacterHomeImages: (...a: unknown[]) => getPublicCharacterHomeImages(...a),
  },
}));

import CharacterHome from '@/pages/CharacterHome';

const FULL_HOME: CharacterHomePublic = {
  id: 59,
  name: 'Pan',
  alias: 'The Ember',
  role: 'immortal king',
  era: 'timeless',
  species: 'human',
  short_bio: 'A tagline for Pan.',
  long_bio: 'A longer paragraph about Pan and the Never Never Realm.',
  tags: 'fantasy, gothic',
  avatar_url: 'https://cdn.test/avatar.png',
  avatar_position_x: 0.5,
  avatar_position_y: 0,
  avatar_scale: 2,
  cover_url: 'https://cdn.test/cover.png',
  cover_position_x: 0.5,
  cover_position_y: 0.075,
  cover_scale: 1,
};

const BARE_HOME: CharacterHomePublic = {
  ...FULL_HOME,
  alias: null, role: null, era: null,
  short_bio: null, long_bio: null, tags: null,
  avatar_url: null, cover_url: null,
};

const POST: CharacterHomePostPublic = {
  id: 7,
  title: null,
  content: 'A good breakfast is always vital',
  content_type: 'IC',
  post_kind: 'general',
  provenance: 'user_written',
  created_at: '2026-07-20T09:00:00Z',
  image_url: null,
  realm_id: 1,
  realm_name: 'The Commons',
};

const IMAGE: CharacterImagePublic = {
  id: 1957,
  character_id: 59,
  kind: 'scene_only',
  url: '/static/generated/x.png',
  created_at: '2026-06-20T07:39:00Z',
};

function renderHome(id = '59') {
  return render(
    <MemoryRouter initialEntries={[`/c/${id}`]}>
      <Routes>
        <Route path="/c/:id" element={<CharacterHome />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(cleanup);

beforeEach(() => {
  vi.clearAllMocks();
  getPublicCharacterHome.mockResolvedValue(FULL_HOME);
  getPublicCharacterHomePosts.mockResolvedValue([]);
  getPublicCharacterHomeImages.mockResolvedValue([]);
});

// ── A. A populated Home renders its content ─────────────────────────────────

describe('populated Home', () => {
  it('renders name, alias, meta line, bio and tags', async () => {
    getPublicCharacterHomePosts.mockResolvedValue([POST]);
    getPublicCharacterHomeImages.mockResolvedValue([IMAGE]);
    renderHome();

    expect(await screen.findByRole('heading', { level: 1, name: 'Pan' })).toBeTruthy();
    expect(screen.getByText('The Ember')).toBeTruthy();
    expect(screen.getByText('immortal king · human · timeless')).toBeTruthy();
    expect(screen.getByText('A tagline for Pan.')).toBeTruthy();
    expect(screen.getByText(/longer paragraph about Pan/)).toBeTruthy();
    expect(screen.getByText('fantasy')).toBeTruthy();
    expect(screen.getByText('gothic')).toBeTruthy();
  });

  it('renders posts and the gallery when both have content', async () => {
    getPublicCharacterHomePosts.mockResolvedValue([POST]);
    getPublicCharacterHomeImages.mockResolvedValue([IMAGE]);
    renderHome();

    expect(await screen.findByText('A good breakfast is always vital')).toBeTruthy();
    expect(screen.getByText('Latest from Pan')).toBeTruthy();
    expect(screen.getByText('Gallery')).toBeTruthy();
    expect(screen.getByText('in The Commons')).toBeTruthy();
  });

  it('requests 20 posts — a history, not a marketing profile', async () => {
    renderHome();
    await screen.findByRole('heading', { level: 1, name: 'Pan' });
    expect(getPublicCharacterHomePosts).toHaveBeenCalledWith(59, 20);
  });

  it('calls exactly the three public endpoints with the id from the route', async () => {
    renderHome();
    await screen.findByRole('heading', { level: 1, name: 'Pan' });
    expect(getPublicCharacterHome).toHaveBeenCalledWith(59);
    expect(getPublicCharacterHomeImages).toHaveBeenCalledWith(59, 24);
  });

  it('renders the closed-beta footer with the character name', async () => {
    renderHome();
    expect(await screen.findByText('Pan has a home on Ficshon.')).toBeTruthy();
    expect(screen.getByText(/closed beta/i)).toBeTruthy();
  });

  it('has no links at all — every route but this one is behind a guard', async () => {
    getPublicCharacterHomePosts.mockResolvedValue([POST]);
    getPublicCharacterHomeImages.mockResolvedValue([IMAGE]);
    const { container } = renderHome();
    await screen.findByRole('heading', { level: 1, name: 'Pan' });

    expect(container.querySelectorAll('a').length).toBe(0);
  });
});

// ── B. Emptiness is omitted, never announced ────────────────────────────────

describe('sparse Home', () => {
  it('omits the About section entirely when bio and tags are empty', async () => {
    getPublicCharacterHome.mockResolvedValue(BARE_HOME);
    renderHome();

    await screen.findByRole('heading', { level: 1, name: 'Pan' });
    expect(screen.queryByText('A tagline for Pan.')).toBeNull();
    expect(screen.queryByText('fantasy')).toBeNull();
  });

  it('omits the Posts section and never says "No Posts Yet"', async () => {
    renderHome();

    await screen.findByRole('heading', { level: 1, name: 'Pan' });
    expect(screen.queryByText('Latest from Pan')).toBeNull();
    expect(screen.queryByText(/no posts yet/i)).toBeNull();
  });

  it('omits the Gallery section and never says "No Media Yet"', async () => {
    renderHome();

    await screen.findByRole('heading', { level: 1, name: 'Pan' });
    expect(screen.queryByText('Gallery')).toBeNull();
    expect(screen.queryByText(/no media yet/i)).toBeNull();
  });

  it('renders a composed page from a name alone', async () => {
    getPublicCharacterHome.mockResolvedValue(BARE_HOME);
    renderHome();

    // Hero and footer survive; nothing apologises for what is missing.
    expect(await screen.findByRole('heading', { level: 1, name: 'Pan' })).toBeTruthy();
    expect(screen.getByText('Pan has a home on Ficshon.')).toBeTruthy();
    expect(screen.queryByText(/yet/i)).toBeNull();
  });

  it('renders whichever meta fields exist, and omits the line when none do', async () => {
    getPublicCharacterHome.mockResolvedValue(BARE_HOME);
    renderHome();
    await screen.findByRole('heading', { level: 1, name: 'Pan' });
    // BARE_HOME still carries species, so the line renders with just that.
    expect(screen.getByText('human')).toBeTruthy();

    cleanup();
    getPublicCharacterHome.mockResolvedValue({ ...BARE_HOME, species: null });
    renderHome();
    await screen.findByRole('heading', { level: 1, name: 'Pan' });
    expect(screen.queryByText('human')).toBeNull();
  });
});

// ── C. Nothing owner-shaped, and no counts ──────────────────────────────────

describe('public surface has no app chrome', () => {
  it('renders no owner controls, tabs or counts', async () => {
    getPublicCharacterHomePosts.mockResolvedValue([POST]);
    getPublicCharacterHomeImages.mockResolvedValue([IMAGE]);
    renderHome();
    await screen.findByRole('heading', { level: 1, name: 'Pan' });

    for (const forbidden of [
      /manage/i, /message/i, /mentions/i, /change cover/i, /add cover/i,
      /reposition/i, /set as avatar/i, /choose image/i, /notifications/i,
      /stories/i, /^posts$/i, /follow/i, /sign in/i, /log in/i, /register/i,
    ]) {
      expect(screen.queryByText(forbidden)).toBeNull();
    }
  });

  it('does not render a post or image count anywhere', async () => {
    getPublicCharacterHomePosts.mockResolvedValue([POST, { ...POST, id: 8 }]);
    getPublicCharacterHomeImages.mockResolvedValue([IMAGE]);
    renderHome();
    await screen.findByRole('heading', { level: 1, name: 'Pan' });

    // The counts would render as bare numerals beside a label; neither exists.
    expect(screen.queryByText('2')).toBeNull();
    expect(screen.queryByText('1')).toBeNull();
  });
});

// ── D. Missing, error and partial-failure states ────────────────────────────

describe('failure states', () => {
  it('renders one indistinguishable state for a 404 and reveals nothing', async () => {
    getPublicCharacterHome.mockRejectedValue(new Error('Character not found'));
    renderHome();

    expect(await screen.findByText(/doesn’t have a public home/i)).toBeTruthy();
    // Must not hint that signing in would reveal more.
    expect(screen.queryByText(/sign in/i)).toBeNull();
    expect(screen.queryByText(/log in/i)).toBeNull();
    expect(screen.queryByText(/private/i)).toBeNull();
    expect(screen.queryByText(/unpublished/i)).toBeNull();
  });

  it('offers a retry on a transport failure', async () => {
    getPublicCharacterHome.mockRejectedValue(new Error('Failed to fetch'));
    renderHome();

    expect(await screen.findByText(/something went wrong/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /try again/i })).toBeTruthy();
  });

  it('renders the Home when posts and images both fail', async () => {
    getPublicCharacterHomePosts.mockRejectedValue(new Error('boom'));
    getPublicCharacterHomeImages.mockRejectedValue(new Error('boom'));
    renderHome();

    expect(await screen.findByRole('heading', { level: 1, name: 'Pan' })).toBeTruthy();
    expect(screen.getByText('A tagline for Pan.')).toBeTruthy();
    expect(screen.queryByText('Gallery')).toBeNull();
  });

  it('renders the gallery when only posts fail', async () => {
    getPublicCharacterHomePosts.mockRejectedValue(new Error('boom'));
    getPublicCharacterHomeImages.mockResolvedValue([IMAGE]);
    renderHome();

    await waitFor(() => expect(screen.getByText('Gallery')).toBeTruthy());
    expect(screen.queryByText('Latest from Pan')).toBeNull();
  });

  it('treats a non-numeric id as missing without calling the API', async () => {
    renderHome('not-a-number');

    expect(await screen.findByText(/doesn’t have a public home/i)).toBeTruthy();
    expect(getPublicCharacterHome).not.toHaveBeenCalled();
  });
});

// ── E. The lightbox keeps a visitor on the Home ─────────────────────────────

describe('gallery lightbox', () => {
  it('opens in place instead of navigating to the raw image URL', async () => {
    getPublicCharacterHomeImages.mockResolvedValue([IMAGE]);
    renderHome();

    await screen.findByText('Gallery');
    expect(screen.queryByRole('dialog')).toBeNull();

    const tile = screen.getAllByRole('button').find((b) => b.querySelector('img'));
    expect(tile).toBeTruthy();
    fireEvent.click(tile!);

    // A dialog, not a navigation: the visitor stays on the Home behind it.
    expect(await screen.findByRole('dialog')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 1, name: 'Pan' })).toBeTruthy();
  });

  it('closes again, returning the visitor to the Home', async () => {
    getPublicCharacterHomeImages.mockResolvedValue([IMAGE]);
    renderHome();

    await screen.findByText('Gallery');
    fireEvent.click(screen.getAllByRole('button').find((b) => b.querySelector('img'))!);
    await screen.findByRole('dialog');

    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull(), { timeout: 1500 });
    expect(screen.getByRole('heading', { level: 1, name: 'Pan' })).toBeTruthy();
  });
});
