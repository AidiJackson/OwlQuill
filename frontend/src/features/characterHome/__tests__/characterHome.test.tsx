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
  social: { comment_count: 0, reactions: {}, comments: [] },
};

type Author = CharacterHomePostPublic['social']['comments'][number]['author'];
const PUBLISHED = (id: number, name: string): Author => ({
  kind: 'character', name, avatar_url: null, character_id: id, linkable: true,
});
const UNPUBLISHED = (name: string): Author => ({
  kind: 'character', name, avatar_url: null, character_id: null, linkable: false,
});
const HIDDEN: Author = {
  kind: 'hidden_character', name: null, avatar_url: null, character_id: null, linkable: false,
};
const WANDERER: Author = {
  kind: 'wanderer', name: null, avatar_url: null, character_id: null, linkable: false,
};
function comment(id: number, content: string, author: Author) {
  return { id, content, provenance: 'user_written', created_at: '2026-07-20T10:00:00Z', author };
}

const SOCIAL_POST: CharacterHomePostPublic = {
  ...POST,
  social: {
    comment_count: 7,
    reactions: { heart: 3, eyes: 2 },
    comments: [
      comment(101, 'Morning, Pan.', PUBLISHED(12, 'Grace')),
      comment(102, 'Watching from the rafters.', UNPUBLISHED('Shadow')),
      comment(103, 'Quietly agreeing.', HIDDEN),
    ],
  },
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

  it('has no links at all when no commenter has a published Home', async () => {
    getPublicCharacterHomePosts.mockResolvedValue([
      POST,
      {
        ...POST,
        id: 8,
        social: {
          comment_count: 3,
          reactions: { star: 1 },
          comments: [
            comment(1, 'a', UNPUBLISHED('Shadow')),
            comment(2, 'b', HIDDEN),
            comment(3, 'c', WANDERER),
          ],
        },
      },
    ]);
    getPublicCharacterHomeImages.mockResolvedValue([IMAGE]);
    const { container } = renderHome();
    await screen.findByText('Shadow');

    expect(container.querySelectorAll('a').length).toBe(0);
  });
});

// ── B2. Social context beneath each post ────────────────────────────────────

describe('post social context', () => {
  async function renderSocial(post: CharacterHomePostPublic = SOCIAL_POST) {
    getPublicCharacterHomePosts.mockResolvedValue([post]);
    const view = renderHome();
    await screen.findByRole('heading', { level: 1, name: 'Pan' });
    await screen.findByText(post.content);
    return view;
  }

  it('links ONLY published commenters, and only to their public Home', async () => {
    const { container } = await renderSocial();
    const links = Array.from(container.querySelectorAll('a'));
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['/c/12']);
    expect(links[0].textContent).toContain('Grace');
    expect(container.querySelector('a[href^="/characters"]')).toBeNull();
  });

  it('names an unpublished PUBLIC commenter without linking them', async () => {
    await renderSocial();
    const shadow = screen.getByText('Shadow');
    expect(shadow.closest('a')).toBeNull();
  });

  it('attributes hidden and Wanderer commenters neutrally, never linked', async () => {
    await renderSocial({
      ...SOCIAL_POST,
      social: {
        comment_count: 2,
        reactions: {},
        comments: [comment(1, 'hidden says', HIDDEN), comment(2, 'wanderer says', WANDERER)],
      },
    });
    expect(screen.getByText('A character').closest('a')).toBeNull();
    expect(screen.getByText('Wanderer').closest('a')).toBeNull();
  });

  it('renders reaction totals as non-interactive, labelled text', async () => {
    const { container } = await renderSocial();
    const social = screen.getByTestId('post-social');

    expect(screen.getByLabelText('3 hearts')).toBeTruthy();
    expect(screen.getByLabelText('2 eyes reactions')).toBeTruthy();
    expect(social.querySelectorAll('button, [role="button"], [tabindex]').length).toBe(0);
    // The only focusable element in the whole block is the published link.
    expect(Array.from(social.querySelectorAll('a, button, input, [tabindex]')).length).toBe(1);
    expect(container.querySelectorAll('button').length).toBe(0);
  });

  it('omits zero reaction types', async () => {
    await renderSocial();
    expect(screen.queryByLabelText(/star/)).toBeNull();
  });

  it('states the comment count truthfully when more exist than are shown', async () => {
    await renderSocial();
    expect(screen.getByText('7 comments')).toBeTruthy();
    expect(screen.getByText('Latest 3 of 7 comments shown')).toBeTruthy();
    expect(screen.queryByText(/show all|view all|load more/i)).toBeNull();
  });

  it('renders the latest comments in the order the server sent them', async () => {
    const { container } = await renderSocial();
    const texts = Array.from(container.querySelectorAll('[data-testid="post-social"] li'))
      .map((li) => li.querySelector('p')?.textContent);
    expect(texts).toEqual(['Morning, Pan.', 'Watching from the rafters.', 'Quietly agreeing.']);
  });

  it('does not add a "shown" line when every comment is shown', async () => {
    await renderSocial({
      ...SOCIAL_POST,
      social: { comment_count: 1, reactions: {}, comments: [comment(1, 'only', WANDERER)] },
    });
    expect(screen.getByText('1 comment')).toBeTruthy();
    expect(screen.queryByText(/comments shown/)).toBeNull();
  });

  it('shows totals alone when there are reactions but no comments', async () => {
    await renderSocial({
      ...SOCIAL_POST,
      social: { comment_count: 0, reactions: { star: 1 }, comments: [] },
    });
    expect(screen.getByLabelText('1 star')).toBeTruthy();
    expect(screen.queryByText(/comment/)).toBeNull();
  });

  it('renders nothing for an empty social block — no zeros, no placeholder', async () => {
    await renderSocial(POST);
    expect(screen.queryByTestId('post-social')).toBeNull();
    for (const announced of [/0 comments/, /no comments/i, /0 reactions/, /no interactions/i, /be the first/i]) {
      expect(screen.queryByText(announced)).toBeNull();
    }
  });

  it('keeps the full post body', async () => {
    const long = 'A very long post. '.repeat(80).trim();
    await renderSocial({ ...SOCIAL_POST, content: long });
    expect(screen.getByText(long)).toBeTruthy();
  });

  it('renders no account identity even if a stray field arrived', async () => {
    const rogue = {
      ...SOCIAL_POST,
      social: {
        ...SOCIAL_POST.social,
        comments: [{
          ...comment(9, 'rogue', WANDERER),
          author: { ...WANDERER, author_username: 'secret_account', user_id: 44 },
          author_username: 'secret_account',
        }],
      },
    } as unknown as CharacterHomePostPublic;
    const { container } = await renderSocial(rogue);
    expect(container.textContent).not.toContain('secret_account');
  });

  it("shows a published commenter's avatar through the image resolver", async () => {
    const { container } = await renderSocial({
      ...SOCIAL_POST,
      social: {
        comment_count: 1,
        reactions: {},
        comments: [comment(1, 'hi', { ...PUBLISHED(12, 'Grace'), avatar_url: '/static/generated/g.png' })],
      },
    });
    const img = container.querySelector('[data-testid="post-social"] img');
    expect(img?.getAttribute('src')).toContain('/static/generated/g.png');
  });

  it("navigates to the commenter's Home and replaces the previous Home's content", async () => {
    await renderSocial();
    getPublicCharacterHome.mockResolvedValue({ ...FULL_HOME, id: 12, name: 'Grace' });
    getPublicCharacterHomePosts.mockResolvedValue([]);
    fireEvent.click(screen.getByRole('link', { name: /Grace/ }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Grace' })).toBeTruthy();
    expect(getPublicCharacterHome).toHaveBeenLastCalledWith(12);
    expect(screen.queryByText(SOCIAL_POST.content)).toBeNull();
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
