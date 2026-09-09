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
 * These are deliberately about the STORED value reaching the DOM. How
 * faithfully a preview frame's aspect ratio predicts the hero's is a separate,
 * unfixed issue (the WYSIWYG mismatch) and is not asserted here.
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

  it('saves exactly those values when nothing is dragged', async () => {
    const onConfirmed = renderPicker();

    await screen.findByText(/drag to reposition/i);
    fireEvent.click(screen.getByRole('button', { name: /set cover/i }));

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
    fireEvent.click(await screen.findByRole('button', { name: /set cover/i }));

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
    fireEvent.click(await screen.findByRole('button', { name: /set cover/i }));

    await waitFor(() => expect(getCharacter).toHaveBeenCalledTimes(2));
    expect(coverImage().style.objectPosition).toBe('25% 80%');
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

    fireEvent.click(screen.getByRole('button', { name: /set cover/i }));

    // One pair of coordinates — no separate mobile value, no extra write.
    await waitFor(() =>
      expect(updateCharacter).toHaveBeenCalledWith(CHARACTER.id, {
        cover_position_x: 0.45,
        cover_position_y: 0.8,
      }),
    );
    expect(updateCharacter).toHaveBeenCalledTimes(1);
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
