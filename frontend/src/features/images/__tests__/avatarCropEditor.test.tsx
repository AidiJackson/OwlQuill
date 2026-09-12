// @vitest-environment jsdom
/**
 * The avatar editor as a CROP TOOL: its words, its hint and cursor for the
 * shape being cropped, reset, one zoom range for both editors, and the two
 * entry points on the character page — Change (a new picture, fresh crop)
 * and Crop (the current picture, opened on its stored crop and saved as
 * framing only). The geometry itself is covered in avatarGeometry.test.ts and
 * avatarCrop.test.tsx and is not restated here.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character } from '@/lib/types';

const getCharacter = vi.fn();
const getMe = vi.fn();
const listCharacterImages = vi.fn();
const getCharacterPosts = vi.fn();
const getCharacterMentions = vi.fn();
const listMyCharacterImages = vi.fn();
const getCharacters = vi.fn();
const updateCharacter = vi.fn();
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
    setCharacterAvatar: (...a: unknown[]) => setCharacterAvatar(...a),
    hasToken: () => true,
    getImageQuota: () => Promise.resolve({ used: 0, limit: null, remaining: null, unlimited: true }),
  },
}));

import CharacterImagePicker from '@/features/images/components/CharacterImagePicker';
import CharacterDetail from '@/pages/CharacterDetail';
import Images from '@/pages/Images';
import { avatarTransformStyle } from '@/lib/media';
import {
  AVATAR_MAX_ZOOM,
  AVATAR_MIN_ZOOM,
  avatarCropAffordance,
  isDefaultAvatarCrop,
} from '@/features/images/avatarCropEditor';

const OWNER = { id: 7, email: 'owner@test.invalid', username: 'owner' };
const AVATAR_URL = 'https://cdn.test/avatar.png';

const CHARACTER: Character = {
  id: 42,
  owner_id: OWNER.id,
  name: 'Taylor',
  species: 'human',
  visibility: 'public',
  cover_url: 'https://cdn.test/cover.png',
  cover_position_x: 0.5,
  cover_position_y: 0.5,
  avatar_url: AVATAR_URL,
  avatar_position_x: 0.5,
  avatar_position_y: 0.5,
  avatar_scale: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const STORED = { avatar_position_x: 0.3, avatar_position_y: 0.1, avatar_scale: 1.5 };

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

const PORTRAIT = { width: 800, height: 1200 };
const LANDSCAPE = { width: 2000, height: 1000 };
const SQUARE = { width: 1000, height: 1000 };

const frame = (): HTMLElement => screen.getByTestId('avatar-preview-frame');
const hint = (): string => screen.getByTestId('avatar-crop-hint').textContent ?? '';
const slider = (): HTMLInputElement => screen.getByRole('slider', { name: /zoom/i }) as HTMLInputElement;
const resetButton = (): HTMLButtonElement => screen.getByRole('button', { name: /reset crop/i }) as HTMLButtonElement;
const previewImage = (): HTMLImageElement => {
  const img = frame().querySelector('img');
  if (!img) throw new Error('the avatar frame has no image');
  return img;
};

const sizeFrame = (el: HTMLElement, width = 160, height = 160) => {
  Object.defineProperty(el, 'offsetWidth', { value: width, configurable: true });
  Object.defineProperty(el, 'offsetHeight', { value: height, configurable: true });
};

const loadImage = (img: HTMLImageElement, { width, height }: { width: number; height: number }) => {
  Object.defineProperty(img, 'naturalWidth', { value: width, configurable: true });
  Object.defineProperty(img, 'naturalHeight', { value: height, configurable: true });
  fireEvent.load(img);
};

const dragBy = (el: HTMLElement, dx: number, dy: number) => {
  fireEvent.mouseDown(el, { clientX: 200, clientY: 200 });
  fireEvent.mouseMove(window, { clientX: 200 + dx, clientY: 200 + dy });
  fireEvent.mouseUp(window);
};

const setZoom = (value: number) => fireEvent.change(slider(), { target: { value: String(value) } });

const expectDefaultCrop = () => {
  expect(previewImage().style.objectPosition).toBe('50% 50%');
  expect(previewImage().style.transform).toBe('');
  expect(slider().value).toBe('1');
};

const renderPicker = (props: Partial<React.ComponentProps<typeof CharacterImagePicker>> = {}) => {
  const onConfirmed = vi.fn();
  render(
    <CharacterImagePicker
      characterId={CHARACTER.id}
      characterName="Taylor"
      mode="avatar"
      onConfirmed={onConfirmed}
      onCancel={vi.fn()}
      {...props}
    />,
  );
  return onConfirmed;
};

/** The picker straight on the current picture, at its stored crop. */
const renderRecrop = () =>
  renderPicker({
    repositionOnly: true,
    currentImageUrl: AVATAR_URL,
    initialPosX: STORED.avatar_position_x,
    initialPosY: STORED.avatar_position_y,
    initialScale: STORED.avatar_scale,
  });

const renderDetail = () =>
  render(
    <MemoryRouter initialEntries={[`/characters/${CHARACTER.id}`]}>
      <Routes>
        <Route path="/characters/:id" element={<CharacterDetail />} />
      </Routes>
    </MemoryRouter>,
  );

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

// ── 1. The words and the cursor, from the geometry ───────────────────────────

describe('avatarCropAffordance', () => {
  it('portrait at zoom 1: vertical only', () => {
    const a = avatarCropAffordance(PORTRAIT, 1, false);
    expect(a.hint).toBe('Drag up or down to position');
    expect(a.free).toEqual({ x: false, y: true });
    expect(a.cursor).toBe('grab');
  });

  it('landscape at zoom 1: horizontal only', () => {
    const a = avatarCropAffordance(LANDSCAPE, 1, false);
    expect(a.hint).toBe('Drag left or right to position');
    expect(a.free).toEqual({ x: true, y: false });
    expect(a.cursor).toBe('grab');
  });

  it('square at zoom 1: nothing to drag, so say zoom', () => {
    const a = avatarCropAffordance(SQUARE, 1, false);
    expect(a.hint).toBe('Zoom in to adjust the crop');
    expect(a.free).toEqual({ x: false, y: false });
    expect(a.cursor).toBe('default');
  });

  it('any shape zoomed: both axes', () => {
    for (const image of [PORTRAIT, LANDSCAPE, SQUARE]) {
      const a = avatarCropAffordance(image, 1.5, false);
      expect(a.hint).toBe('Drag to position');
      expect(a.free).toEqual({ x: true, y: true });
    }
  });

  it('size not yet known: assume draggable', () => {
    const a = avatarCropAffordance(null, 1, false);
    expect(a.hint).toBe('Drag to position');
    expect(a.cursor).toBe('grab');
  });

  it('cursor: grab with a free axis, grabbing while dragging, default when locked even mid-press', () => {
    expect(avatarCropAffordance(PORTRAIT, 1, true).cursor).toBe('grabbing');
    expect(avatarCropAffordance(SQUARE, 1, true).cursor).toBe('default');
  });
});

describe('isDefaultAvatarCrop', () => {
  it('is exactly 0.5 / 0.5 / 1', () => {
    expect(isDefaultAvatarCrop(0.5, 0.5, 1)).toBe(true);
    expect(isDefaultAvatarCrop(0.5, 0.5, 1.01)).toBe(false);
    expect(isDefaultAvatarCrop(0.49, 0.5, 1)).toBe(false);
    expect(isDefaultAvatarCrop(0.5, 0.51, 1)).toBe(false);
  });
});

// ── 2. The picker as a crop tool ─────────────────────────────────────────────

describe('CharacterImagePicker — crop tool', () => {
  it('is titled as a crop of the profile picture and saves as one', async () => {
    renderRecrop();
    await screen.findByTestId('avatar-preview-frame');
    expect(screen.getByRole('heading', { name: /crop profile picture · taylor/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /^save profile picture$/i })).toBeTruthy();
    expect(screen.queryByText(/save position/i)).toBeNull();
    expect(screen.getByText('The original image is never altered.')).toBeTruthy();
  });

  it('the hint follows the loaded shape and the zoom', async () => {
    renderPicker({ repositionOnly: true, currentImageUrl: AVATAR_URL });
    await screen.findByTestId('avatar-preview-frame');
    expect(hint()).toBe('Drag to position'); // size unknown yet

    loadImage(previewImage(), PORTRAIT);
    await waitFor(() => expect(hint()).toBe('Drag up or down to position'));

    setZoom(1.5);
    await waitFor(() => expect(hint()).toBe('Drag to position'));

    setZoom(1);
    await waitFor(() => expect(hint()).toBe('Drag up or down to position'));
  });

  it('landscape and square hints at zoom 1', async () => {
    renderPicker({ repositionOnly: true, currentImageUrl: AVATAR_URL });
    await screen.findByTestId('avatar-preview-frame');
    loadImage(previewImage(), LANDSCAPE);
    await waitFor(() => expect(hint()).toBe('Drag left or right to position'));

    cleanup();
    renderPicker({ repositionOnly: true, currentImageUrl: AVATAR_URL });
    await screen.findByTestId('avatar-preview-frame');
    loadImage(previewImage(), SQUARE);
    await waitFor(() => expect(hint()).toBe('Zoom in to adjust the crop'));
  });

  it('cursor: grab on a free axis, grabbing while pressed, default when nothing moves', async () => {
    renderPicker({ repositionOnly: true, currentImageUrl: AVATAR_URL });
    await screen.findByTestId('avatar-preview-frame');
    loadImage(previewImage(), PORTRAIT);
    sizeFrame(frame());
    await waitFor(() => expect(frame().style.cursor).toBe('grab'));

    fireEvent.mouseDown(frame(), { clientX: 200, clientY: 200 });
    await waitFor(() => expect(frame().style.cursor).toBe('grabbing'));
    fireEvent.mouseUp(window);
    await waitFor(() => expect(frame().style.cursor).toBe('grab'));

    cleanup();
    renderPicker({ repositionOnly: true, currentImageUrl: AVATAR_URL });
    await screen.findByTestId('avatar-preview-frame');
    loadImage(previewImage(), SQUARE);
    await waitFor(() => expect(frame().style.cursor).toBe('default'));
    setZoom(2);
    await waitFor(() => expect(frame().style.cursor).toBe('grab'));
  });

  it('Reset crop is available only when the crop differs from the default, and restores exactly it', async () => {
    renderPicker({ repositionOnly: true, currentImageUrl: AVATAR_URL });
    await screen.findByTestId('avatar-preview-frame');
    expect(resetButton().disabled).toBe(true);

    loadImage(previewImage(), PORTRAIT);
    sizeFrame(frame());
    dragBy(frame(), 0, 24); // Y → 0.2
    await waitFor(() => expect(previewImage().style.objectPosition).toBe('50% 20%'));
    expect(resetButton().disabled).toBe(false);

    fireEvent.click(resetButton());
    await waitFor(() => expectDefaultCrop());
    expect(resetButton().disabled).toBe(true);

    setZoom(2); // zoom alone is also a non-default crop
    await waitFor(() => expect(resetButton().disabled).toBe(false));
    fireEvent.click(resetButton());
    await waitFor(() => expectDefaultCrop());
  });

  it('opens on the stored crop when re-cropping, without snapping', async () => {
    renderRecrop();
    await screen.findByTestId('avatar-preview-frame');
    const expected = avatarTransformStyle(STORED.avatar_scale, STORED.avatar_position_x, STORED.avatar_position_y);
    expect(previewImage().style.objectPosition).toBe(expected.objectPosition);
    expect(previewImage().style.transform).toBe(expected.transform);
    expect(slider().value).toBe('1.5');
    expect(resetButton().disabled).toBe(false);
  });

  it('re-crop saves framing only: PATCH the triple, never assign an image', async () => {
    const onConfirmed = renderRecrop();
    await screen.findByTestId('avatar-preview-frame');
    setZoom(2);

    fireEvent.click(screen.getByRole('button', { name: /save profile picture/i }));

    await waitFor(() =>
      expect(updateCharacter).toHaveBeenCalledWith(CHARACTER.id, {
        avatar_position_x: STORED.avatar_position_x,
        avatar_position_y: STORED.avatar_position_y,
        avatar_scale: 2,
      }),
    );
    expect(setCharacterAvatar).not.toHaveBeenCalled();
    await waitFor(() => expect(onConfirmed).toHaveBeenCalledWith({ avatar_url: AVATAR_URL }));
  });

  it('choosing a different picture starts its crop at 0.5 / 0.5 / 1, not the previous framing', async () => {
    renderPicker({
      initialPosX: STORED.avatar_position_x,
      initialPosY: STORED.avatar_position_y,
      initialScale: STORED.avatar_scale,
    });
    const thumb = (await screen.findByText(/choose from taylor's images/i)).parentElement!.querySelector('button')!;
    fireEvent.click(thumb);
    await screen.findByTestId('avatar-preview-frame');
    expectDefaultCrop();
    expect(resetButton().disabled).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: /save profile picture/i }));
    await waitFor(() => expect(setCharacterAvatar).toHaveBeenCalledWith(CHARACTER.id, 'character', LIBRARY_IMAGE.id));
    await waitFor(() =>
      expect(updateCharacter).toHaveBeenCalledWith(CHARACTER.id, {
        avatar_position_x: 0.5,
        avatar_position_y: 0.5,
        avatar_scale: 1,
      }),
    );
  });

  it('arrow keys nudge along a free axis only, and never past the edge', async () => {
    renderPicker({ repositionOnly: true, currentImageUrl: AVATAR_URL });
    await screen.findByTestId('avatar-preview-frame');
    loadImage(previewImage(), PORTRAIT); // overflowY 80 at zoom 1
    sizeFrame(frame());

    fireEvent.keyDown(frame(), { key: 'ArrowRight' }); // fitted axis: nothing
    fireEvent.keyDown(frame(), { key: 'ArrowDown' }); // 4px down → Y − 0.05
    await waitFor(() => expect(previewImage().style.objectPosition).toBe('50% 45%'));

    for (let i = 0; i < 20; i += 1) fireEvent.keyDown(frame(), { key: 'ArrowUp', shiftKey: true }); // 16px each, far past the edge
    await waitFor(() => expect(previewImage().style.objectPosition).toBe('50% 100%'));
    expect(previewImage().style.transform).toBe('');
  });
});

// ── 3. One zoom range for both editors ───────────────────────────────────────

describe('zoom range', () => {
  it('keeps the library\'s former maximum so an avatar already saved at 3 stays representable', () => {
    expect(AVATAR_MIN_ZOOM).toBe(1);
    expect(AVATAR_MAX_ZOOM).toBe(3);
  });

  it('the picker uses it', async () => {
    renderPicker({ repositionOnly: true, currentImageUrl: AVATAR_URL, initialScale: 3 });
    await screen.findByTestId('avatar-preview-frame');
    expect(slider().min).toBe('1');
    expect(slider().max).toBe('3');
    expect(slider().value).toBe('3');
    expect(previewImage().style.transform).toBe(avatarTransformStyle(3, 0.5, 0.5).transform);
  });

  it('the library uses the same range and shape', async () => {
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
    expect(slider().min).toBe('1');
    expect(slider().max).toBe('3');
    expect(frame().className).toContain('rounded-2xl');
    expect(frame().className).not.toContain('rounded-full');
    expect(screen.getByText(/crop profile picture/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /save profile picture/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /reset crop/i })).toBeTruthy();
  });
});

// ── 4. Change vs Crop on the character page ──────────────────────────────────

describe('CharacterDetail — Change and Crop', () => {
  it('Crop opens the current picture on its stored crop', async () => {
    getCharacter.mockResolvedValue({ ...CHARACTER, ...STORED });
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: /crop profile picture/i }));
    await screen.findByTestId('avatar-preview-frame');
    expect(previewImage().src).toBe(AVATAR_URL);
    expect(previewImage().style.objectPosition).toBe('30% 10%');
    expect(previewImage().style.transform).toBe(avatarTransformStyle(1.5, 0.3, 0.1).transform);
    expect(slider().value).toBe('1.5');
    expect(screen.queryByText(/choose from taylor's images/i)).toBeNull();
  });

  it('Change offers other pictures and starts a chosen one at the default crop', async () => {
    getCharacter.mockResolvedValue({ ...CHARACTER, ...STORED });
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: /change profile picture/i }));
    const thumb = (await screen.findByText(/choose from taylor's images/i)).parentElement!.querySelector('button')!;
    expect(screen.queryByTestId('avatar-preview-frame')).toBeNull();
    fireEvent.click(thumb);
    await screen.findByTestId('avatar-preview-frame');
    expectDefaultCrop();
  });
});
