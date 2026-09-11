// @vitest-environment jsdom
//
// A DOM suite because the whole subject is what gets RENDERED — an
// `object-position` string on an <img> — and which value the editors send when
// the creator presses Save. Neither is reachable from pure functions. The
// suite-wide default in vitest.config.ts stays `node`.
/**
 * Cover framing: shown from the stored value, edited from the stored value,
 * and never quietly recentred.
 *
 * A character's cover framing is two fractions, `cover_position_x/y`, applied
 * as CSS `object-position` under `object-fit: cover`. Three defects made a
 * correctly-saved value look lost, and each has a test here:
 *
 * 1. **The authenticated page kept a stale copy.** After a successful
 *    reposition, `CharacterDetail` merged only the image url into its local
 *    character and never the new framing, so the hero re-rendered from the
 *    PRE-DRAG values and the cover visibly snapped back the instant the
 *    creator pressed Save. The save had worked; the page said otherwise. It
 *    now refetches and lets the server be authoritative — so the test asserts
 *    the SERVER's value reaches the hero, not the picker's.
 * 2. **The library's cover editor always opened centred.** It writes
 *    `cover_position_x/y` on save, so opening at 0.5/0.5 meant that merely
 *    visiting it and pressing Save discarded the creator's composition.
 * 3. **Nothing asserted the public Home applied the value at all.** The
 *    existing Home suite carries a non-centre `cover_position_y` in its
 *    fixture and never checks that it lands on the element.
 *
 * Two more joined later:
 *
 * 4. **The gallery's "Set as Cover" recentred the framing.** The client sent
 *    an explicit 0.5/0.5 whenever the caller gave none, so the server's
 *    "omitted means preserve" rule never fired. The page then kept its stale
 *    framing until a reload revealed the reset.
 * 5. **The preview assumed the free axis from the viewport.** Which axis
 *    `object-fit: cover` leaves slack on depends on the image's shape against
 *    the frame's, so a wide landscape on the desktop preview could only move
 *    sideways while the hint said "vertical", and moved far slower than the
 *    pointer. The drag now follows the real image (`coverGeometry`).
 *
 * These are deliberately about the STORED value reaching the DOM. How
 * faithfully a preview frame's aspect ratio predicts the hero's is a separate
 * issue (the WYSIWYG approximation) and is not asserted here.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character, CharacterHomePublic } from '@/lib/types';

// ── apiClient double ─────────────────────────────────────────────────────────
// One mock for every surface under test. Each test arranges only the calls its
// own page makes; the rest resolve empty so a page never hangs on a pending
// promise it does not care about.
const getCharacter = vi.fn();
const getMe = vi.fn();
const listCharacterImages = vi.fn();
const getCharacterPosts = vi.fn();
const getCharacterMentions = vi.fn();
const listMyCharacterImages = vi.fn();
const getCharacters = vi.fn();
const updateCharacter = vi.fn();
const setCharacterCover = vi.fn();
const setCharacterAvatar = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    getCharacter: (...a: unknown[]) => getCharacter(...a),
    getMe: (...a: unknown[]) => getMe(...a),
    listCharacterImages: (...a: unknown[]) => listCharacterImages(...a),
    getCharacterPosts: (...a: unknown[]) => getCharacterPosts(...a),
    getCharacterMentions: (...a: unknown[]) => getCharacterMentions(...a),
    listMyCharacterImages: (...a: unknown[]) => listMyCharacterImages(...a),
    getCharacters: (...a: unknown[]) => getCharacters(...a),
    updateCharacter: (...a: unknown[]) => updateCharacter(...a),
    setCharacterCover: (...a: unknown[]) => setCharacterCover(...a),
    setCharacterAvatar: (...a: unknown[]) => setCharacterAvatar(...a),
    // The auth store asks this synchronously at module scope; it is not part of
    // what these tests are about, so it simply answers "signed in".
    hasToken: () => true,
    // The library page renders a quota strip. Irrelevant here, but it must
    // resolve or the page throws during commit.
    getImageQuota: () => Promise.resolve({ used: 0, limit: null, remaining: null, unlimited: true }),
  },
}));

import CharacterHomeHero from '@/features/characterHome/components/CharacterHomeHero';
import CharacterImagePicker from '@/features/images/components/CharacterImagePicker';
import CharacterDetail from '@/pages/CharacterDetail';
import Images from '@/pages/Images';

const OWNER = { id: 7, email: 'owner@test.invalid', username: 'owner' };

const CHARACTER: Character = {
  id: 42,
  owner_id: OWNER.id,
  name: 'Shadow',
  species: 'wolf',
  visibility: 'public',
  cover_url: 'https://cdn.test/cover.png',
  cover_position_x: 0.25,
  cover_position_y: 0.8,
  avatar_url: 'https://cdn.test/avatar.png',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

/**
 * The cover <img> — the first image carrying an `object-position`.
 *
 * Document order matters and is relied on: the hero's cover is rendered before
 * the picker modal, so while the picker is open (its preview carries an
 * object-position too) this still returns the HERO's image, which is the one
 * every assertion here is about.
 */
const coverImage = (): HTMLImageElement => {
  const img = Array.from(document.querySelectorAll<HTMLImageElement>('img')).find(
    (el) => el.style.objectPosition,
  );
  if (!img) throw new Error('no image with an object-position was rendered');
  return img;
};

/** The shared preview frame — the drag surface CoverFramingPreview owns. */
const previewFrame = (): HTMLElement => screen.getByTestId('cover-preview-frame');

/** The <img> inside the shared preview specifically (not the page hero). */
const previewImage = (): HTMLImageElement => {
  const img = previewFrame().querySelector('img');
  if (!img) throw new Error('the preview frame has no image');
  return img;
};

/**
 * Give the frame real dimensions.
 *
 * jsdom reports `offsetWidth`/`offsetHeight` as 0 for everything, and the drag
 * hook divides the pointer delta by them — so without this every drag produces
 * Infinity and no test could distinguish a working drag from a broken one.
 */
const sizeFrame = (el: HTMLElement, width: number, height: number) => {
  Object.defineProperty(el, 'offsetWidth', { value: width, configurable: true });
  Object.defineProperty(el, 'offsetHeight', { value: height, configurable: true });
};

/**
 * Tell the preview what shape its image is. jsdom never decodes an image, so
 * `naturalWidth/Height` stay 0 and `load` never fires; this supplies both,
 * which is exactly what the preview reads to decide the free axis.
 */
const loadPreviewImage = (width: number, height: number) => {
  const img = previewImage();
  Object.defineProperty(img, 'naturalWidth', { value: width, configurable: true });
  Object.defineProperty(img, 'naturalHeight', { value: height, configurable: true });
  fireEvent.load(img);
};

/** A complete pointer drag across the frame, in CSS pixels. */
const dragBy = (el: HTMLElement, dx: number, dy: number) => {
  fireEvent.mouseDown(el, { clientX: 200, clientY: 200 });
  fireEvent.mouseMove(window, { clientX: 200 + dx, clientY: 200 + dy });
  fireEvent.mouseUp(window);
};

const clickViewport = (name: 'Desktop' | 'Mobile') =>
  fireEvent.click(screen.getByRole('button', { name }));

beforeEach(() => {
  vi.clearAllMocks();
  getMe.mockResolvedValue(OWNER);
  listCharacterImages.mockResolvedValue([]);
  getCharacterPosts.mockResolvedValue([]);
  getCharacterMentions.mockResolvedValue([]);
  listMyCharacterImages.mockResolvedValue([]);
  getCharacters.mockResolvedValue([]);
  updateCharacter.mockResolvedValue({});
});

afterEach(cleanup);

// ── 1. The public Home applies the stored framing ────────────────────────────

describe('CharacterHomeHero', () => {
  const home = (over: Partial<CharacterHomePublic> = {}): CharacterHomePublic =>
    ({
      id: 42,
      name: 'Shadow',
      cover_url: 'https://cdn.test/cover.png',
      cover_position_x: 0.25,
      cover_position_y: 0.8,
      ...over,
    }) as CharacterHomePublic;

  it('renders object-position from the stored cover_position_x/y', () => {
    render(<CharacterHomeHero character={home()} />);
    expect(coverImage().style.objectPosition).toBe('25% 80%');
  });

  it('falls back to centre when the character was never positioned', () => {
    render(
      <CharacterHomeHero
        character={home({ cover_position_x: undefined, cover_position_y: undefined })}
      />,
    );
    expect(coverImage().style.objectPosition).toBe('50% 50%');
  });

  it('keeps a 0 edge value instead of coalescing it to centre', () => {
    // 0 is falsy, so a `||` fallback anywhere in this path would silently turn
    // a cover framed hard to the top into a centred one.
    render(<CharacterHomeHero character={home({ cover_position_y: 0 })} />);
    expect(coverImage().style.objectPosition).toBe('25% 0%');
  });
});

// ── 2. The picker opens on, and saves, the supplied framing ──────────────────

describe('CharacterImagePicker — reposition only', () => {
  const renderPicker = (onConfirmed = vi.fn()) => {
    render(
      <CharacterImagePicker
        characterId={CHARACTER.id}
        characterName="Shadow"
        mode="cover"
        repositionOnly
        currentImageUrl="https://cdn.test/cover.png"
        initialPosX={0.25}
        initialPosY={0.8}
        onConfirmed={onConfirmed}
        onCancel={vi.fn()}
      />,
    );
    return onConfirmed;
  };

  it('opens on the framing it was given, not centred', async () => {
    renderPicker();
    await waitFor(() => expect(coverImage().style.objectPosition).toBe('25% 80%'));
  });

  it('is labelled as saving a position, not as setting a cover', async () => {
    // Reposition-only writes framing through PATCH and never changes which
    // image is the cover; a "Set cover" button on the current cover read as
    // a re-assignment that might reset something.
    renderPicker();
    await screen.findByText(/drag to reposition/i);
    expect(screen.getByRole('button', { name: 'Save position' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /set cover/i })).toBeNull();
    expect(screen.getByRole('heading', { level: 2 }).textContent).toMatch(/^Reposition cover/);
  });

  it('still says "Set cover" when choosing a new image', async () => {
    render(
      <CharacterImagePicker
        characterId={CHARACTER.id}
        characterName="Shadow"
        mode="cover"
        onConfirmed={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(await screen.findByRole('button', { name: 'Set cover' })).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2 }).textContent).toMatch(/^Cover image/);
  });

  it('saves exactly those values when nothing is dragged', async () => {
    const onConfirmed = renderPicker();

    await screen.findByText(/drag to reposition/i);
    fireEvent.click(screen.getByRole('button', { name: /save position/i }));

    await waitFor(() =>
      expect(updateCharacter).toHaveBeenCalledWith(CHARACTER.id, {
        cover_position_x: 0.25,
        cover_position_y: 0.8,
      }),
    );
    // Repositioning must not re-run the governed image setter — that endpoint
    // also writes framing, and calling it here would be a second, redundant
    // write of the value this call just made.
    expect(setCharacterCover).not.toHaveBeenCalled();
    await waitFor(() => expect(onConfirmed).toHaveBeenCalled());
  });
});

// ── 3. The authenticated page shows what the SERVER persisted ────────────────

describe('CharacterDetail after a reposition', () => {
  const renderDetail = () =>
    render(
      <MemoryRouter initialEntries={[`/characters/${CHARACTER.id}`]}>
        <Routes>
          <Route path="/characters/:id" element={<CharacterDetail />} />
        </Routes>
      </MemoryRouter>,
    );

  it('re-reads the character and renders the persisted framing', async () => {
    // The server is authoritative: it reports 0.4/0.9 after the save. If the
    // page manufactured its own state, or kept the pre-drag copy, the hero
    // would show 25% 80% — the exact stale-state bug this guards.
    getCharacter
      .mockResolvedValueOnce(CHARACTER)
      .mockResolvedValue({ ...CHARACTER, cover_position_x: 0.4, cover_position_y: 0.9 });

    renderDetail();
    await waitFor(() => expect(coverImage().style.objectPosition).toBe('25% 80%'));

    fireEvent.click(await screen.findByTitle(/reposition cover/i));
    fireEvent.click(await screen.findByRole('button', { name: /save position/i }));

    await waitFor(() => expect(coverImage().style.objectPosition).toBe('40% 90%'));
    expect(getCharacter).toHaveBeenCalledTimes(2);
  });

  it('keeps the last known framing when the refetch fails', async () => {
    // A failed READ must not blank or recentre a cover the creator can see.
    getCharacter
      .mockResolvedValueOnce(CHARACTER)
      .mockRejectedValue(new Error('network'));

    renderDetail();
    await waitFor(() => expect(coverImage().style.objectPosition).toBe('25% 80%'));

    fireEvent.click(await screen.findByTitle(/reposition cover/i));
    fireEvent.click(await screen.findByRole('button', { name: /save position/i }));

    await waitFor(() => expect(getCharacter).toHaveBeenCalledTimes(2));
    expect(coverImage().style.objectPosition).toBe('25% 80%');
  });
});

// ── 3b. The gallery's "Set as Cover" leaves the framing alone ─────────────────

describe('CharacterDetail gallery "Set as Cover"', () => {
  const GALLERY_IMAGE = {
    id: 900,
    character_id: CHARACTER.id,
    kind: 'generated',
    url: 'https://cdn.test/gallery.png',
    created_at: '2026-01-01T00:00:00Z',
  };

  const renderDetailOnMedia = async () => {
    getCharacter.mockResolvedValue(CHARACTER);
    listCharacterImages.mockResolvedValue([GALLERY_IMAGE]);
    render(
      <MemoryRouter initialEntries={[`/characters/${CHARACTER.id}`]}>
        <Routes>
          <Route path="/characters/:id" element={<CharacterDetail />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(coverImage().style.objectPosition).toBe('25% 80%'));
    fireEvent.click(screen.getByRole('button', { name: 'Media' }));
    return screen.findByRole('button', { name: /set as cover/i });
  };

  it('sends no framing, so the server preserves it, and the hero keeps it', async () => {
    // The server answers with the framing it KEPT. Before the fix the client
    // sent 0.5/0.5 here and the row was recentred.
    setCharacterCover.mockResolvedValue({
      cover_url: GALLERY_IMAGE.url,
      cover_position_x: 0.25,
      cover_position_y: 0.8,
    });
    fireEvent.click(await renderDetailOnMedia());

    await waitFor(() => expect(setCharacterCover).toHaveBeenCalledTimes(1));
    // Exactly three arguments: no framing was manufactured on the way out.
    expect(setCharacterCover.mock.calls[0]).toEqual([CHARACTER.id, 'character', GALLERY_IMAGE.id]);
    expect(updateCharacter).not.toHaveBeenCalled();

    await waitFor(() => expect(coverImage().getAttribute('src')).toBe(GALLERY_IMAGE.url));
    expect(coverImage().style.objectPosition).toBe('25% 80%');
  });

  it('renders whatever framing the server reports as effective, not its own copy', async () => {
    // If the server ever does change the framing (a never-positioned row
    // reads back as centre), the hero shows THAT — the response is the truth,
    // the pre-call state is not.
    setCharacterCover.mockResolvedValue({
      cover_url: GALLERY_IMAGE.url,
      cover_position_x: 0.5,
      cover_position_y: 0.5,
    });
    fireEvent.click(await renderDetailOnMedia());
    await waitFor(() => expect(coverImage().style.objectPosition).toBe('50% 50%'));
  });
});

// ── 4. The library's cover editor opens on the saved framing ─────────────────

describe('Images — cover editor', () => {
  const LIBRARY_IMAGE = {
    id: 900,
    character_id: CHARACTER.id,
    kind: 'generated',
    status: 'active',
    visibility: 'private',
    file_path: 'https://cdn.test/lib.png',
    url: 'https://cdn.test/lib.png',
    prompt_summary: 'A library image',
    created_at: '2026-01-01T00:00:00Z',
  };

  it('initialises the drag from the character’s existing framing, not centre', async () => {
    // This editor WRITES cover_position_x/y on save. Opening centred meant
    // that visiting it and pressing Save silently discarded the creator's
    // composition — so where it opens is the whole guarantee.
    getCharacters.mockResolvedValue([CHARACTER]);
    listMyCharacterImages.mockResolvedValue([LIBRARY_IMAGE]);

    render(
      <MemoryRouter initialEntries={['/images']}>
        <Routes>
          <Route path="/images" element={<Images />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByTitle(/click to view or use this image/i));
    fireEvent.click(await screen.findByRole('button', { name: /set as cover/i }));

    await waitFor(() => expect(coverImage().style.objectPosition).toBe('25% 80%'));
  });

  it('uses the shared desktop/mobile preview, not a legacy frame of its own', async () => {
    // The two editors write the same two numbers; showing them different
    // frames is how they came to disagree in the first place.
    getCharacters.mockResolvedValue([CHARACTER]);
    listMyCharacterImages.mockResolvedValue([LIBRARY_IMAGE]);

    render(
      <MemoryRouter initialEntries={['/images']}>
        <Routes>
          <Route path="/images" element={<Images />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByTitle(/click to view or use this image/i));
    fireEvent.click(await screen.findByRole('button', { name: /set as cover/i }));

    const frame = await screen.findByTestId('cover-preview-frame');
    expect(frame.dataset.viewport).toBe('desktop');
    expect(frame.className).toContain('aspect-[16/9]');

    clickViewport('Mobile');
    expect(previewFrame().dataset.viewport).toBe('mobile');
    // Still the saved framing — switching viewport is not an edit.
    expect(previewImage().style.objectPosition).toBe('25% 80%');
  });
});

// ── 5. The shared desktop/mobile preview ─────────────────────────────────────

describe('CoverFramingPreview, through the picker', () => {
  const renderCoverPicker = (onConfirmed = vi.fn()) => {
    render(
      <CharacterImagePicker
        characterId={CHARACTER.id}
        characterName="Shadow"
        mode="cover"
        repositionOnly
        currentImageUrl="https://cdn.test/cover.png"
        initialPosX={0.25}
        initialPosY={0.8}
        onConfirmed={onConfirmed}
        onCancel={vi.fn()}
      />,
    );
    return onConfirmed;
  };

  it('opens on the desktop viewport', async () => {
    renderCoverPicker();
    const frame = await screen.findByTestId('cover-preview-frame');
    expect(frame.dataset.viewport).toBe('desktop');
  });

  it('renders the intended geometry for each viewport', async () => {
    // 16/9 ≈ 1.78 sits between the authenticated (~1.74) and public (~1.83)
    // heroes; 3/4 = 0.75 between their mobile counterparts (~0.68 / ~0.74).
    // The mobile frame is width-constrained so it fits the dialog's max-h.
    renderCoverPicker();
    const frame = await screen.findByTestId('cover-preview-frame');
    expect(frame.className).toContain('aspect-[16/9]');
    expect(frame.className).toContain('w-full');

    clickViewport('Mobile');
    expect(previewFrame().className).toContain('aspect-[3/4]');
    expect(previewFrame().className).toContain('w-[210px]');
  });

  it('preserves X and Y exactly across desktop → mobile → desktop', async () => {
    renderCoverPicker();
    await screen.findByTestId('cover-preview-frame');
    expect(previewImage().style.objectPosition).toBe('25% 80%');

    clickViewport('Mobile');
    expect(previewImage().style.objectPosition).toBe('25% 80%');

    clickViewport('Desktop');
    expect(previewImage().style.objectPosition).toBe('25% 80%');
  });

  it('writes nothing merely because the viewport changed', async () => {
    renderCoverPicker();
    await screen.findByTestId('cover-preview-frame');

    clickViewport('Mobile');
    clickViewport('Desktop');
    clickViewport('Mobile');

    expect(updateCharacter).not.toHaveBeenCalled();
    expect(setCharacterCover).not.toHaveBeenCalled();
    expect(setCharacterAvatar).not.toHaveBeenCalled();
  });

  it('drags in mobile and shows the same shared values back in desktop', async () => {
    // The point of the toggle: X is what a phone actually frames with, and the
    // old single wide preview left it pinned and unreachable.
    renderCoverPicker();
    const frame = await screen.findByTestId('cover-preview-frame');

    clickViewport('Mobile');
    sizeFrame(previewFrame(), 200, 267);
    dragBy(previewFrame(), -40, 0); // dx = -40/200 = -0.2 → posX 0.25 + 0.2

    await waitFor(() =>
      expect(previewImage().style.objectPosition).toBe('45% 80%'),
    );

    clickViewport('Desktop');
    expect(previewImage().style.objectPosition).toBe('45% 80%');
    expect(frame).toBeTruthy();
  });

  it('persists the shared pair when saved while mobile is active', async () => {
    renderCoverPicker();
    await screen.findByTestId('cover-preview-frame');

    clickViewport('Mobile');
    sizeFrame(previewFrame(), 200, 267);
    dragBy(previewFrame(), -40, 0);
    await waitFor(() =>
      expect(previewImage().style.objectPosition).toBe('45% 80%'),
    );

    fireEvent.click(screen.getByRole('button', { name: /save position/i }));

    // One pair of coordinates — no separate mobile value, no extra write.
    await waitFor(() =>
      expect(updateCharacter).toHaveBeenCalledWith(CHARACTER.id, {
        cover_position_x: 0.45,
        cover_position_y: 0.8,
      }),
    );
    expect(updateCharacter).toHaveBeenCalledTimes(1);
  });

  describe('follows the image\'s real free axis', () => {
    // Frames sized to the viewports' nominal ratios so overflows are exact:
    // desktop 320×180 (16:9), mobile 210×280 (3:4).
    const DESKTOP = [320, 180] as const;
    const MOBILE = [210, 280] as const;

    it('a wide landscape on desktop moves sideways 1:1 and not at all vertically — the reported defect', async () => {
      renderCoverPicker();
      await screen.findByTestId('cover-preview-frame');
      loadPreviewImage(2000, 1000); // 2:1 — wider than 16:9
      sizeFrame(previewFrame(), ...DESKTOP); // scaled 360×180 → overflowX 40

      expect(previewFrame().dataset.freeX).toBe('true');
      expect(previewFrame().dataset.freeY).toBe('false');
      expect(screen.getByTestId('cover-framing-hint').textContent).toMatch(/left or right/i);
      expect(screen.getByTestId('cover-framing-hint').textContent).not.toMatch(/vertical/i);

      dragBy(previewFrame(), 0, -60); // vertical: the fitted axis
      await new Promise((r) => setTimeout(r, 0));
      expect(previewImage().style.objectPosition).toBe('25% 80%');

      dragBy(previewFrame(), -10, 0); // 10px of a 40px overflow → +0.25
      await waitFor(() => expect(previewImage().style.objectPosition).toBe('50% 80%'));
    });

    it('a portrait on desktop moves vertically 1:1 and not at all sideways', async () => {
      renderCoverPicker();
      await screen.findByTestId('cover-preview-frame');
      loadPreviewImage(800, 1200); // 2:3
      sizeFrame(previewFrame(), ...DESKTOP); // scaled 320×480 → overflowY 300

      expect(previewFrame().dataset.freeX).toBe('false');
      expect(previewFrame().dataset.freeY).toBe('true');
      expect(screen.getByTestId('cover-framing-hint').textContent).toMatch(/up or down/i);

      dragBy(previewFrame(), 80, 0); // horizontal: fitted
      await new Promise((r) => setTimeout(r, 0));
      expect(previewImage().style.objectPosition).toBe('25% 80%');

      dragBy(previewFrame(), 0, 30); // down 30px of 300 → −0.1
      await waitFor(() => expect(previewImage().style.objectPosition).toBe('25% 70%'));
    });

    it('a square flips its free axis between desktop and mobile', async () => {
      renderCoverPicker();
      await screen.findByTestId('cover-preview-frame');
      loadPreviewImage(1000, 1000);
      expect(previewFrame().dataset.freeY).toBe('true');
      expect(previewFrame().dataset.freeX).toBe('false');

      clickViewport('Mobile');
      expect(previewFrame().dataset.freeX).toBe('true');
      expect(previewFrame().dataset.freeY).toBe('false');
      expect(screen.getByTestId('cover-framing-hint').textContent).toMatch(/left or right/i);

      sizeFrame(previewFrame(), ...MOBILE); // scaled 280×280 → overflowX 70
      dragBy(previewFrame(), 7, 0); // right 7px of 70 → −0.1
      await waitFor(() => expect(previewImage().style.objectPosition).toBe('15% 80%'));
    });

    it('an image the shape of the viewport has nothing to adjust and does not move', async () => {
      renderCoverPicker();
      await screen.findByTestId('cover-preview-frame');
      loadPreviewImage(1600, 900);
      sizeFrame(previewFrame(), ...DESKTOP);

      expect(previewFrame().dataset.freeX).toBe('false');
      expect(previewFrame().dataset.freeY).toBe('false');
      expect(screen.getByTestId('cover-framing-hint').textContent).toMatch(/nothing to adjust/i);

      dragBy(previewFrame(), -100, -100);
      await new Promise((r) => setTimeout(r, 0));
      expect(previewImage().style.objectPosition).toBe('25% 80%');
      expect(updateCharacter).not.toHaveBeenCalled();
    });

    it('a diagonal drag never leaks into the fitted axis — X and Y are not swapped', async () => {
      renderCoverPicker();
      await screen.findByTestId('cover-preview-frame');
      loadPreviewImage(2000, 1000);
      sizeFrame(previewFrame(), ...DESKTOP); // overflowX 40, overflowY 0

      dragBy(previewFrame(), -20, -20);
      await waitFor(() => expect(previewImage().style.objectPosition).toBe('75% 80%'));
    });

    it('before the image reports a size, the hint is neutral and a drag still works', async () => {
      renderCoverPicker();
      await screen.findByTestId('cover-preview-frame');
      expect(previewFrame().dataset.freeX).toBeUndefined();
      expect(screen.getByTestId('cover-framing-hint').textContent).toBe('Drag the image to adjust its framing.');
    });
  });

  it('is absent in avatar mode — an avatar is square on every screen', async () => {
    render(
      <CharacterImagePicker
        characterId={CHARACTER.id}
        characterName="Shadow"
        mode="avatar"
        repositionOnly
        currentImageUrl="https://cdn.test/avatar.png"
        onConfirmed={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    await screen.findByText(/drag to reposition/i);
    expect(screen.queryByTestId('cover-preview-frame')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Desktop' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Mobile' })).toBeNull();
    // The avatar's own control is untouched.
    expect(screen.getByText(/zoom/i)).toBeTruthy();
  });
});
