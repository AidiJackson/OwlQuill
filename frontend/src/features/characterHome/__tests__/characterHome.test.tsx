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

  it('omits the meta line when no meta field exists', async () => {
    getPublicCharacterHome.mockResolvedValue({ ...BARE_HOME, species: null });
    renderHome();
    await screen.findByRole('heading', { level: 1, name: 'Pan' });
    expect(screen.queryByText('human')).toBeNull();
  });
});

// ── B2. The hero meta line, and the one value that says nothing ─────────────

/**
 * `role · species · era` composes from whatever the server sent — with a single
 * exception. A character whose ONLY populated field is `species: human` gets no
 * meta line at all, because a lone "HUMAN" above the name reads as a database
 * column rather than an introduction.
 *
 * The exception is deliberately narrow, and these tests are what keeps it that
 * way. It must not widen into "hide species", which would cost every non-human
 * character its one distinguishing word, and it must not widen into "hide
 * human", which would punch a hole in the middle of a composed line.
 */
describe('hero meta line', () => {
  const meta = (over: Partial<CharacterHomePublic>) => ({
    ...BARE_HOME, role: null, species: null, era: null, ...over,
  });

  it('omits the line when human is the only value', async () => {
    getPublicCharacterHome.mockResolvedValue(meta({ species: 'human' }));
    renderHome();
    await screen.findByRole('heading', { level: 1, name: 'Pan' });
    expect(screen.queryByText('human')).toBeNull();
  });

  it('matches the generic value case-insensitively and ignores surrounding space', async () => {
    for (const species of ['Human', 'HUMAN', '  human  ']) {
      getPublicCharacterHome.mockResolvedValue(meta({ species }));
      renderHome();
      await screen.findByRole('heading', { level: 1, name: 'Pan' });
      expect(screen.queryByText(/human/i)).toBeNull();
      cleanup();
    }
  });

  it('keeps a distinctive species standing alone', async () => {
    // The whole point of the field for anyone who is not human. A character
    // with nothing else filled in still gets to say what they are.
    for (const species of ['Fae', 'revenant', 'half-human']) {
      getPublicCharacterHome.mockResolvedValue(meta({ species }));
      renderHome();
      await screen.findByRole('heading', { level: 1, name: 'Pan' });
      expect(screen.getByText(species)).toBeTruthy();
      cleanup();
    }
  });

  it('keeps human when it is composed with a role or an era', async () => {
    getPublicCharacterHome.mockResolvedValue(meta({ role: 'innkeeper', species: 'human' }));
    renderHome();
    await screen.findByRole('heading', { level: 1, name: 'Pan' });
    expect(screen.getByText('innkeeper · human')).toBeTruthy();

    cleanup();
    getPublicCharacterHome.mockResolvedValue(meta({ species: 'human', era: 'the long winter' }));
    renderHome();
    await screen.findByRole('heading', { level: 1, name: 'Pan' });
    expect(screen.getByText('human · the long winter')).toBeTruthy();
  });

  it('still renders a role or era that stands alone', async () => {
    getPublicCharacterHome.mockResolvedValue(meta({ role: 'immortal king' }));
    renderHome();
    await screen.findByRole('heading', { level: 1, name: 'Pan' });
    expect(screen.getByText('immortal king')).toBeTruthy();
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

  /**
   * The close control has to sit on the picture.
   *
   * It is absolutely positioned against its panel, so the panel's box and the
   * drawn image have to be the same rectangle. They were not: `w-full` on the
   * image forced the box to the panel's full 672px while `object-contain` drew
   * a portrait photo at ~578px inside it, and the button — correctly placed at
   * the box's top-right — landed in the backdrop, clear of the photo. Every
   * image in a character gallery is portrait, so it happened every time.
   *
   * jsdom runs no layout engine and loads no Tailwind, so the gutter itself
   * cannot be measured here. What these assertions pin is its cause, which is
   * the part a future edit would reintroduce.
   */
  async function openLightbox() {
    getPublicCharacterHomeImages.mockResolvedValue([IMAGE]);
    renderHome();
    await screen.findByText('Gallery');
    fireEvent.click(screen.getAllByRole('button').find((b) => b.querySelector('img'))!);
    const dialog = await screen.findByRole('dialog');
    const closeButton = screen.getByRole('button', { name: /close/i });
    return { dialog, closeButton, image: dialog.querySelector('img')! };
  }

  it('anchors the close control to the image box, not a wider container', async () => {
    const { closeButton, image } = await openLightbox();
    const panel = closeButton.parentElement!;

    // One box holds both, so "top-right of the panel" is "top-right of the
    // photo" — but only while the panel shrink-wraps the image.
    expect(panel.contains(image)).toBe(true);
    expect(panel.className).toContain('relative');
    expect(panel.className).toContain('w-fit');
    expect(panel.className).not.toMatch(/\bw-full\b/);

    // The image must size itself from its own aspect ratio. A forced full width
    // is exactly what reopens the gap between the box and the drawn pixels.
    expect(image.className).not.toMatch(/\bw-full\b/);
    expect(image.className).toMatch(/max-h-\[85vh\]/);
  });

  it('still lets the image span a phone screen', async () => {
    const { image } = await openLightbox();
    // The cap is `min(panel width, viewport − margins)`, so on a narrow screen
    // the viewport term wins and the image fills it — the same result the old
    // `w-full mx-4` gave. Pinned as written because the viewport term is the
    // half that mobile depends on.
    expect(image.className).toContain('max-w-[min(42rem,calc(100vw-2rem))]');
  });
});

// ── F. The Home holds still while the lightbox is open ──────────────────────

/**
 * Scroll lock.
 *
 * Without it the page scrolls behind the backdrop under a wheel or a touch
 * drag, and closing the lightbox drops the visitor somewhere they never chose
 * to be. What these tests care about as much as the lock is the RESTORE: a
 * component that leaves `overflow: hidden` behind has frozen the whole site,
 * and it fails silently — the lightbox itself still looks correct.
 */
describe('lightbox scroll lock', () => {
  /** Give jsdom, which lays nothing out, a viewport with a scrollbar in it. */
  function withScrollbar(width: number) {
    Object.defineProperty(window, 'innerWidth', {
      value: 1000, writable: true, configurable: true,
    });
    Object.defineProperty(document.documentElement, 'clientWidth', {
      value: 1000 - width, writable: true, configurable: true,
    });
  }

  afterEach(() => {
    document.body.style.overflow = '';
    document.body.style.paddingRight = '';
    Object.defineProperty(document.documentElement, 'clientWidth', {
      value: 0, writable: true, configurable: true,
    });
  });

  async function open() {
    getPublicCharacterHomeImages.mockResolvedValue([IMAGE]);
    const view = renderHome();
    await screen.findByText('Gallery');
    fireEvent.click(screen.getAllByRole('button').find((b) => b.querySelector('img'))!);
    await screen.findByRole('dialog');
    return view;
  }

  it('locks the body while open and unlocks it on close', async () => {
    await open();
    expect(document.body.style.overflow).toBe('hidden');

    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull(), { timeout: 1500 });
    expect(document.body.style.overflow).toBe('');
  });

  it('unlocks when the lightbox unmounts mid-transition', async () => {
    const { unmount } = await open();
    expect(document.body.style.overflow).toBe('hidden');

    // A visitor navigating away between the close click and the 200ms unmount
    // must not leave a frozen document behind.
    unmount();
    expect(document.body.style.overflow).toBe('');
  });

  it('restores a pre-existing inline value rather than clearing it', async () => {
    // Restoring means putting back exactly what was there. Blanking the
    // property instead would quietly discard another owner's setting.
    document.body.style.overflow = 'auto';
    document.body.style.paddingRight = '7px';

    const { unmount } = await open();
    expect(document.body.style.overflow).toBe('hidden');

    unmount();
    expect(document.body.style.overflow).toBe('auto');
    expect(document.body.style.paddingRight).toBe('7px');
  });

  it('pads for the vanishing scrollbar so the page does not jump sideways', async () => {
    withScrollbar(15);
    const { unmount } = await open();
    // Hiding overflow removes the scrollbar and widens the viewport; the page
    // would shift left by its width without this.
    expect(document.body.style.paddingRight).toBe('15px');

    unmount();
    expect(document.body.style.paddingRight).toBe('');
  });

  it('adds the scrollbar width to padding the body already had', async () => {
    withScrollbar(15);
    document.body.style.paddingRight = '10px';
    const { unmount } = await open();
    expect(document.body.style.paddingRight).toBe('25px');

    unmount();
    expect(document.body.style.paddingRight).toBe('10px');
  });

  it('locks without padding when there is no scrollbar to compensate for', async () => {
    // Phones, and any environment that reports no layout. The lock is the part
    // that must always apply; the compensation is only ever a nicety.
    withScrollbar(0);
    await open();
    expect(document.body.style.overflow).toBe('hidden');
    expect(document.body.style.paddingRight).toBe('');
  });
});
