// @vitest-environment jsdom
/**
 * Avatar crop: what the editors let the creator reach, what they save, and
 * that the saved triple renders the same everywhere.
 *
 * THE DEFECT. The picker cover-fitted the source into its square with the
 * browser's default centre `object-position`, and its drag only ever spanned
 * the overflow that ZOOMING added — and refused to start at zoom 1 at all. A
 * portrait's top sixth was therefore unreachable at any zoom: the pixels were
 * in the source, the maths could not show them, and zooming cropped more of
 * everything else while exposing the same proportion. The stored position now
 * spans the TOTAL overflow (cover fit plus zoom), so a portrait pans
 * vertically at zoom 1, a landscape horizontally, and zoom widens the range
 * rather than unlocking it. See `avatarGeometry`.
 *
 * `avatarTransformStyle` is the ONE implementation both editors and both
 * renderers use, so the last group asserts identity of the rendered style
 * across all four for the same stored values.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character, CharacterHomePublic } from '@/lib/types';

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
    hasToken: () => true,
    getImageQuota: () => Promise.resolve({ used: 0, limit: null, remaining: null, unlimited: true }),
  },
}));

import CharacterHomeHero from '@/features/characterHome/components/CharacterHomeHero';
import CharacterImagePicker from '@/features/images/components/CharacterImagePicker';
import CharacterDetail from '@/pages/CharacterDetail';
import Images from '@/pages/Images';
import { avatarTransformStyle } from '@/lib/media';

const OWNER = { id: 7, email: 'owner@test.invalid', username: 'owner' };

const CHARACTER: Character = {
  id: 42,
  owner_id: OWNER.id,
  name: 'Taylor',
  species: 'human',
  visibility: 'public',
  cover_url: 'https://cdn.test/cover.png',
  cover_position_x: 0.5,
  cover_position_y: 0.5,
  avatar_url: 'https://cdn.test/avatar.png',
  avatar_position_x: 0.5,
  avatar_position_y: 0.5,
  avatar_scale: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

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

const frame = (): HTMLElement => screen.getByTestId('avatar-preview-frame');
const previewImage = (): HTMLImageElement => {
  const img = frame().querySelector('img');
  if (!img) throw new Error('the avatar frame has no image');
  return img;
};

/** jsdom lays nothing out; give the frame the editors' real 160×160. */
const sizeFrame = (el: HTMLElement, width = 160, height = 160) => {
  Object.defineProperty(el, 'offsetWidth', { value: width, configurable: true });
  Object.defineProperty(el, 'offsetHeight', { value: height, configurable: true });
};

/** jsdom decodes nothing; supply the natural size and fire `load`. */
const loadImage = (img: HTMLImageElement, width: number, height: number) => {
  Object.defineProperty(img, 'naturalWidth', { value: width, configurable: true });
  Object.defineProperty(img, 'naturalHeight', { value: height, configurable: true });
  fireEvent.load(img);
};

const dragBy = (el: HTMLElement, dx: number, dy: number) => {
  fireEvent.mouseDown(el, { clientX: 200, clientY: 200 });
  fireEvent.mouseMove(window, { clientX: 200 + dx, clientY: 200 + dy });
  fireEvent.mouseUp(window);
};

const setZoom = (value: number) => fireEvent.change(screen.getByRole('slider'), { target: { value: String(value) } });

const settle = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  vi.clearAllMocks();
  getMe.mockResolvedValue(OWNER);
  getCharacter.mockResolvedValue(CHARACTER);
  listCharacterImages.mockResolvedValue([]);
  getCharacterPosts.mockResolvedValue([]);
  getCharacterMentions.mockResolvedValue([]);
  listMyCharacterImages.mockResolvedValue([LIBRARY_IMAGE]);
  getCharacters.mockResolvedValue([CHARACTER]);
  updateCharacter.mockResolvedValue({});
  setCharacterAvatar.mockResolvedValue({ avatar_url: LIBRARY_IMAGE.url });
});

afterEach(cleanup);

// ── 1. The picker's avatar cropper ───────────────────────────────────────────

describe('CharacterImagePicker — avatar crop', () => {
  const renderAvatarPicker = (onConfirmed = vi.fn()) => {
    render(
      <CharacterImagePicker
        characterId={CHARACTER.id}
        characterName="Taylor"
        mode="avatar"
        repositionOnly
        currentImageUrl="https://cdn.test/avatar.png"
        onConfirmed={onConfirmed}
        onCancel={vi.fn()}
      />,
    );
    return onConfirmed;
  };

  it('opens centred at zoom 1 with no transform — the unchanged default', async () => {
    renderAvatarPicker();
    await screen.findByTestId('avatar-preview-frame');
    expect(previewImage().style.objectPosition).toBe('50% 50%');
    expect(previewImage().style.transform).toBe('');
  });

  it('portrait at zoom 1: drags up to reveal the head, and not sideways — the reported defect', async () => {
    renderAvatarPicker();
    await screen.findByTestId('avatar-preview-frame');
    loadImage(previewImage(), 800, 1200); // cover-fit 160×240, overflowY 80
    sizeFrame(frame());

    dragBy(frame(), 40, 0); // sideways: fitted axis
    await settle();
    expect(previewImage().style.objectPosition).toBe('50% 50%');

    dragBy(frame(), 0, 24); // down 24px of an 80px overflow → Y 0.5 − 0.3 = 0.2
    await waitFor(() => expect(previewImage().style.objectPosition).toBe('50% 20%'));
    expect(previewImage().style.transform).toBe(''); // still zoom 1: no transform needed

    dragBy(frame(), 0, 200); // the whole way: the top edge, and no further
    await waitFor(() => expect(previewImage().style.objectPosition).toBe('50% 0%'));
  });

  it('landscape at zoom 1: drags sideways, and not vertically', async () => {
    renderAvatarPicker();
    await screen.findByTestId('avatar-preview-frame');
    loadImage(previewImage(), 2000, 1000); // cover-fit 320×160, overflowX 160
    sizeFrame(frame());

    dragBy(frame(), 0, 40);
    await settle();
    expect(previewImage().style.objectPosition).toBe('50% 50%');

    dragBy(frame(), -16, 0); // left 16px of 160 → X 0.5 + 0.1
    await waitFor(() => expect(previewImage().style.objectPosition).toBe('60% 50%'));
  });

  it('square at zoom 1: fills the square exactly, so nothing moves', async () => {
    renderAvatarPicker();
    await screen.findByTestId('avatar-preview-frame');
    loadImage(previewImage(), 1000, 1000);
    sizeFrame(frame());

    dragBy(frame(), -50, -50);
    await settle();
    expect(previewImage().style.objectPosition).toBe('50% 50%');
  });

  it('zooming ADDS range: a square becomes draggable on both axes, 1:1 over the zoom overflow', async () => {
    renderAvatarPicker();
    await screen.findByTestId('avatar-preview-frame');
    loadImage(previewImage(), 1000, 1000);
    sizeFrame(frame());
    setZoom(2); // overflow (2−1)·160 = 160 on both axes

    dragBy(frame(), -16, 16); // left 16 → X +0.1; down 16 → Y −0.1
    await waitFor(() => expect(previewImage().style.objectPosition).toBe('60% 40%'));
    expect(previewImage().style.transform).toBe(avatarTransformStyle(2, 0.6, 0.4).transform);
  });

  it('zoomed portrait: vertical range grows to cover fit × zoom plus zoom overflow', async () => {
    renderAvatarPicker();
    await screen.findByTestId('avatar-preview-frame');
    loadImage(previewImage(), 800, 1200);
    sizeFrame(frame());
    setZoom(1.5); // Y: 1.5·80 + 0.5·160 = 200; X: 0.5·160 = 80

    dragBy(frame(), -8, 20); // X +0.1, Y −0.1
    await waitFor(() => expect(previewImage().style.objectPosition).toBe('60% 40%'));
  });

  it('never exposes blank space: the fraction is clamped to [0, 1] on every axis', async () => {
    renderAvatarPicker();
    await screen.findByTestId('avatar-preview-frame');
    loadImage(previewImage(), 800, 1200);
    sizeFrame(frame());
    setZoom(2);

    dragBy(frame(), 9999, 9999); // far past the top-left edge
    await waitFor(() => expect(previewImage().style.objectPosition).toBe('0% 0%'));
    dragBy(frame(), -9999, -9999);
    await waitFor(() => expect(previewImage().style.objectPosition).toBe('100% 100%'));
  });

  it('before the image reports its size, zoom 1 stays put and zoom still pans (the safe fallback)', async () => {
    renderAvatarPicker();
    await screen.findByTestId('avatar-preview-frame');
    sizeFrame(frame());

    dragBy(frame(), -40, -40);
    await settle();
    expect(previewImage().style.objectPosition).toBe('50% 50%');

    setZoom(2);
    dragBy(frame(), -16, 0);
    await waitFor(() => expect(previewImage().style.objectPosition).toBe('60% 50%'));
  });

  it('saves the framed position and zoom after setting the image', async () => {
    const onConfirmed = vi.fn();
    render(
      <CharacterImagePicker
        characterId={CHARACTER.id}
        characterName="Taylor"
        mode="avatar"
        onConfirmed={onConfirmed}
        onCancel={vi.fn()}
      />,
    );
    // Choose the library image (its thumbnail button), then frame it.
    const thumb = (await screen.findByText(/choose from taylor's images/i)).parentElement!.querySelector('button')!;
    fireEvent.click(thumb);
    await screen.findByTestId('avatar-preview-frame');
    loadImage(previewImage(), 800, 1200);
    sizeFrame(frame());
    dragBy(frame(), 0, 24); // Y → 0.2 at zoom 1
    await waitFor(() => expect(previewImage().style.objectPosition).toBe('50% 20%'));
    setZoom(1.5);

    fireEvent.click(screen.getByRole('button', { name: /set profile picture/i }));

    await waitFor(() => expect(setCharacterAvatar).toHaveBeenCalledWith(CHARACTER.id, 'character', LIBRARY_IMAGE.id));
    await waitFor(() =>
      expect(updateCharacter).toHaveBeenCalledWith(CHARACTER.id, {
        avatar_position_x: 0.5,
        avatar_position_y: 0.2,
        avatar_scale: 1.5,
      }),
    );
    await waitFor(() => expect(onConfirmed).toHaveBeenCalledWith({ avatar_url: LIBRARY_IMAGE.url }));
  });
});

// ── 2. The library's avatar editor — same maths, same save ───────────────────

describe('Images — avatar editor', () => {
  const openAvatarEditor = async () => {
    render(
      <MemoryRouter initialEntries={['/images']}>
        <Routes>
          <Route path="/images" element={<Images />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByTitle(/click to view or use this image/i));
    fireEvent.click(await screen.findByRole('button', { name: /set as profile picture/i }));
    await screen.findByTestId('avatar-preview-frame');
  };

  it('pans a portrait vertically at zoom 1 through the shared style', async () => {
    await openAvatarEditor();
    loadImage(previewImage(), 800, 1200);
    sizeFrame(frame());

    dragBy(frame(), 40, 0);
    await settle();
    expect(previewImage().style.objectPosition).toBe('50% 50%');

    dragBy(frame(), 0, 24);
    await waitFor(() => expect(previewImage().style.objectPosition).toBe('50% 20%'));
    expect(previewImage().style.transform).toBe('');
  });

  it('saves the framed position and zoom', async () => {
    await openAvatarEditor();
    loadImage(previewImage(), 2000, 1000);
    sizeFrame(frame());
    dragBy(frame(), -16, 0); // X → 0.6 at zoom 1
    await waitFor(() => expect(previewImage().style.objectPosition).toBe('60% 50%'));
    setZoom(2);

    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    await waitFor(() => expect(setCharacterAvatar).toHaveBeenCalledWith(CHARACTER.id, 'character', LIBRARY_IMAGE.id));
    await waitFor(() =>
      expect(updateCharacter).toHaveBeenCalledWith(CHARACTER.id, {
        avatar_position_x: 0.6,
        avatar_position_y: 0.5,
        avatar_scale: 2,
      }),
    );
  });
});

// ── 3. One implementation: editor preview = character page = public Home ─────

describe('the saved crop renders identically everywhere', () => {
  const STORED = { avatar_scale: 1.5, avatar_position_x: 0.3, avatar_position_y: 0.1 };
  const expected = avatarTransformStyle(STORED.avatar_scale, STORED.avatar_position_x, STORED.avatar_position_y);

  const avatarImage = (): HTMLImageElement => {
    const img = screen.getByAltText('Taylor') as HTMLImageElement;
    if (!img.src.endsWith('avatar.png')) throw new Error('not the avatar');
    return img;
  };

  it('CharacterDetail applies the stored triple through avatarTransformStyle', async () => {
    getCharacter.mockResolvedValue({ ...CHARACTER, ...STORED });
    render(
      <MemoryRouter initialEntries={[`/characters/${CHARACTER.id}`]}>
        <Routes>
          <Route path="/characters/:id" element={<CharacterDetail />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(avatarImage().style.transform).toBe(expected.transform));
    expect(avatarImage().style.objectPosition).toBe(expected.objectPosition);
  });

  it('CharacterHomeHero applies the same', () => {
    render(
      <CharacterHomeHero
        character={{ id: 42, name: 'Taylor', avatar_url: 'https://cdn.test/avatar.png', ...STORED } as CharacterHomePublic}
      />,
    );
    expect(avatarImage().style.transform).toBe(expected.transform);
    expect(avatarImage().style.objectPosition).toBe(expected.objectPosition);
  });

  it('the picker preview shows the same for the same values', async () => {
    render(
      <CharacterImagePicker
        characterId={CHARACTER.id}
        characterName="Taylor"
        mode="avatar"
        repositionOnly
        currentImageUrl="https://cdn.test/avatar.png"
        initialPosX={STORED.avatar_position_x}
        initialPosY={STORED.avatar_position_y}
        onConfirmed={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    await screen.findByTestId('avatar-preview-frame');
    setZoom(STORED.avatar_scale);
    await waitFor(() => expect(previewImage().style.transform).toBe(expected.transform));
    expect(previewImage().style.objectPosition).toBe(expected.objectPosition);
  });

  it('a never-repositioned avatar (0.5/0.5/1) is a plain centred cover crop with no transform', () => {
    render(
      <CharacterHomeHero
        character={{ id: 42, name: 'Taylor', avatar_url: 'https://cdn.test/avatar.png', avatar_scale: null, avatar_position_x: null, avatar_position_y: null } as CharacterHomePublic}
      />,
    );
    expect(avatarImage().style.objectPosition).toBe('50% 50%');
    expect(avatarImage().style.transform).toBe('');
  });
});
