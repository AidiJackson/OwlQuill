// @vitest-environment jsdom
/**
 * Avatar + cover management on CharacterDetail — Polish Phase 5.5 (PD-6).
 *
 * One owner path for the avatar (the picker, on the canonical POST route, a
 * fresh crop per new image, framing through PATCH), one for the cover, and a
 * Remove for each that clears the association and deletes no image. The
 * picker asks the SERVER which images are eligible. The lightbox's old
 * "Set as avatar" — legacy route, silent failure, inherited framing — is gone;
 * it now hands the image to the picker.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character, User } from '@/lib/types';

const getCharacter = vi.fn();
const getMe = vi.fn();
const listCharacterImages = vi.fn();
const listMyCharacterImages = vi.fn();
const setCharacterAvatar = vi.fn();
const setCharacterCover = vi.fn();
const updateCharacter = vi.fn();
const removeCharacterAvatar = vi.fn();
const removeCharacterCover = vi.fn();
const getCharacters = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    getCharacter: (...a: unknown[]) => getCharacter(...a),
    getMe: (...a: unknown[]) => getMe(...a),
    listCharacterImages: (...a: unknown[]) => listCharacterImages(...a),
    listMyCharacterImages: (...a: unknown[]) => listMyCharacterImages(...a),
    setCharacterAvatar: (...a: unknown[]) => setCharacterAvatar(...a),
    setCharacterCover: (...a: unknown[]) => setCharacterCover(...a),
    updateCharacter: (...a: unknown[]) => updateCharacter(...a),
    removeCharacterAvatar: (...a: unknown[]) => removeCharacterAvatar(...a),
    removeCharacterCover: (...a: unknown[]) => removeCharacterCover(...a),
    getCharacters: (...a: unknown[]) => getCharacters(...a),
    getCharacterPosts: () => Promise.resolve([]),
    getCharacterMentions: () => Promise.resolve([]),
    hasToken: () => true,
  },
}));

import CharacterDetail from '@/pages/CharacterDetail';
import Characters from '@/pages/Characters';
import { useAuthStore } from '@/lib/store';
import characterDetailSource from '../CharacterDetail.tsx?raw';
import charactersSource from '../Characters.tsx?raw';
import pickerSource from '../../features/images/components/CharacterImagePicker.tsx?raw';
import sharedApiSource from '../../features/characterCreation/shared/api.ts?raw';

const ME = { id: 7, email: 'me@test.invalid', username: 'me', character_count: 1, writer_unlocked: true } as unknown as User;

const WITH_MEDIA: Character = {
  id: 42, name: 'Taylor', species: 'human', visibility: 'public', is_owner: true, owner_id: 7,
  avatar_url: 'https://cdn.test/avatar.png', avatar_position_x: 0.2, avatar_position_y: 0.8, avatar_scale: 1.6,
  cover_url: 'https://cdn.test/cover.png', cover_position_x: 0.1, cover_position_y: 0.9, cover_scale: 1,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
} as Character;

const FRESH: Character = {
  ...WITH_MEDIA, avatar_url: undefined, cover_url: undefined,
  avatar_position_x: 0.5, avatar_position_y: 0.5, avatar_scale: 1, cover_position_x: 0.5, cover_position_y: 0.5,
} as Character;

const VISITOR_VIEW: Character = { ...WITH_MEDIA, id: 43, name: 'Morgan', is_owner: false, owner_id: null } as Character;

const FACE_CARD = { id: 901, character_id: 42, kind: 'identity_face_front', status: 'active', visibility: 'private',
  file_path: 'https://cdn.test/face.png', url: 'https://cdn.test/face.png', prompt_summary: 'front face card', created_at: '' };
const GENERATED = { id: 902, character_id: 42, kind: 'generated', status: 'active', visibility: 'private',
  file_path: 'https://cdn.test/gen.png', url: 'https://cdn.test/gen.png', prompt_summary: 'a scene', created_at: '' };

function renderDetail(id = 42) {
  return render(
    <MemoryRouter initialEntries={[`/characters/${id}`]}>
      <Routes>
        <Route path="/characters/:id" element={<CharacterDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

async function openManage(name = 'Taylor') {
  await screen.findByRole('heading', { name });
  fireEvent.click(await screen.findByRole('button', { name: 'Manage' }));
  return screen.getByRole('region', { name: /Profile picture & cover/ });
}

const dialog = () => screen.getByRole('dialog');

beforeEach(() => {
  vi.clearAllMocks();
  getMe.mockResolvedValue(ME);
  getCharacter.mockImplementation((id: number) => Promise.resolve(id === 43 ? VISITOR_VIEW : WITH_MEDIA));
  listCharacterImages.mockResolvedValue([GENERATED]);
  listMyCharacterImages.mockResolvedValue([FACE_CARD, GENERATED]);
  getCharacters.mockResolvedValue([WITH_MEDIA]);
  updateCharacter.mockResolvedValue({});
  setCharacterAvatar.mockResolvedValue({ avatar_url: FACE_CARD.url });
  setCharacterCover.mockResolvedValue({ cover_url: GENERATED.url, cover_position_x: 0.5, cover_position_y: 0.5 });
  useAuthStore.setState({ user: { ...ME, active_character: { id: 42, name: 'Taylor', avatar_url: WITH_MEDIA.avatar_url } } as unknown as User, status: 'authenticated' });
});
afterEach(cleanup);

describe('who sees management', () => {
  it('owner sees profile picture and cover management with current media', async () => {
    renderDetail();
    const section = await openManage();
    const avatar = within(section).getByTestId('manage-avatar-preview').querySelector('img') as HTMLImageElement;
    expect(avatar.getAttribute('src')).toBe(WITH_MEDIA.avatar_url);
    // Persisted framing is what renders — not a default.
    expect(avatar.style.objectPosition).toBe('20% 80%');
    expect(avatar.style.transform).toContain('1.6');
    const cover = within(section).getByTestId('manage-cover-preview').querySelector('img') as HTMLImageElement;
    expect(cover.getAttribute('src')).toBe(WITH_MEDIA.cover_url);
    expect(cover.style.objectPosition).toBe('10% 90%');
    for (const name of ['Change picture', 'Crop', 'Remove picture', 'Change cover', 'Reposition', 'Remove cover']) {
      expect(within(section).getByRole('button', { name })).toBeTruthy();
    }
  });

  it('a fresh character offers Choose and no Remove', async () => {
    getCharacter.mockResolvedValue(FRESH);
    renderDetail();
    const section = await openManage();
    expect(within(section).getByRole('button', { name: 'Choose picture' })).toBeTruthy();
    expect(within(section).getByRole('button', { name: 'Choose cover' })).toBeTruthy();
    expect(within(section).queryByRole('button', { name: 'Remove picture' })).toBeNull();
    expect(within(section).queryByRole('button', { name: 'Remove cover' })).toBeNull();
  });

  it('non-owner sees none of it', async () => {
    renderDetail(43);
    await screen.findByRole('heading', { name: 'Morgan' });
    await screen.findByRole('button', { name: 'Message' });
    expect(screen.queryByRole('button', { name: 'Manage' })).toBeNull();
    expect(screen.queryByRole('region', { name: /Profile picture & cover/ })).toBeNull();
    for (const name of [/Change picture|Choose picture/, /Remove picture/, /Change cover|Add cover/, /Remove cover/, /Crop profile picture/, /Change profile picture/]) {
      expect(screen.queryByRole('button', { name })).toBeNull();
    }
  });

  it('ownership is never decided from owner_id, and the legacy set-avatar path is gone (source pins)', () => {
    for (const [file, src] of [['CharacterDetail.tsx', characterDetailSource], ['CharacterImagePicker.tsx', pickerSource]] as const) {
      expect(src, file).not.toMatch(/owner_id\s*[=!]==?/);
      expect(src, file).not.toMatch(/[=!]==?\s*[\w.]*owner_id/);
    }
    expect(characterDetailSource).not.toMatch(/\/set-avatar|from '@\/features\/characterCreation\/shared\/api'.*setCharacterAvatar/);
    expect(sharedApiSource).not.toMatch(/\/set-avatar/);
    expect(pickerSource).not.toMatch(/GALLERY_KINDS|ELIGIBLE_KINDS/);
    expect(charactersSource).not.toMatch(/\.portrait_url/); // the read, not the comment explaining its retirement
  });
});

describe('choosing an avatar — the one canonical path', () => {
  it('asks the server for avatar-eligible images and offers a canon face card', async () => {
    renderDetail();
    const section = await openManage();
    fireEvent.click(within(section).getByRole('button', { name: 'Change picture' }));
    await waitFor(() => expect(listMyCharacterImages).toHaveBeenCalledWith(
      expect.objectContaining({ characterId: 42, eligibleFor: 'avatar' }),
    ));
    expect(listMyCharacterImages.mock.calls[0][0]).not.toHaveProperty('kind');
    expect(await screen.findByTestId('picker-image-901')).toBeTruthy(); // the face card
    expect(screen.getByTestId('picker-image-902')).toBeTruthy();
  });

  it('a new picture starts from the default crop, not the previous picture\'s framing, and saves via the canonical route', async () => {
    const refreshed = { ...WITH_MEDIA, avatar_url: FACE_CARD.url, avatar_position_x: 0.5, avatar_position_y: 0.5, avatar_scale: 1 };
    getCharacter.mockResolvedValueOnce(WITH_MEDIA).mockResolvedValueOnce(refreshed);
    renderDetail();
    const section = await openManage();
    fireEvent.click(within(section).getByRole('button', { name: 'Change picture' }));
    fireEvent.click(await screen.findByTestId('picker-image-901'));
    expect(screen.getByTestId('picker-image-901').getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Save profile picture' }));

    await waitFor(() => expect(setCharacterAvatar).toHaveBeenCalledWith(42, 'character', 901));
    // Framing is written by PATCH, and it is the DEFAULT crop — the stored
    // 0.2/0.8/1.6 belonged to the old picture and must not carry over.
    await waitFor(() => expect(updateCharacter).toHaveBeenCalledWith(42, {
      avatar_position_x: 0.5, avatar_position_y: 0.5, avatar_scale: 1,
    }));
    // Page adopts the server's copy, then the sidebar is refreshed quietly.
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(getCharacter).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(getMe).toHaveBeenCalledTimes(2));
  });

  it('re-cropping opens on the persisted framing and never re-assigns the image', async () => {
    renderDetail();
    const section = await openManage();
    fireEvent.click(within(section).getByRole('button', { name: 'Crop' }));
    const d = dialog();
    expect(within(d).getByText('Crop profile picture')).toBeTruthy();
    expect(listMyCharacterImages).not.toHaveBeenCalled();
    fireEvent.click(within(d).getByRole('button', { name: 'Save profile picture' }));
    await waitFor(() => expect(updateCharacter).toHaveBeenCalledWith(42, {
      avatar_position_x: 0.2, avatar_position_y: 0.8, avatar_scale: 1.6,
    }));
    expect(setCharacterAvatar).not.toHaveBeenCalled();
  });

  it('the gallery lightbox hands the image to the picker instead of writing on its own', async () => {
    renderDetail();
    await screen.findByRole('heading', { name: 'Taylor' });
    fireEvent.click(screen.getByRole('button', { name: 'Media' }));
    const thumb = await screen.findByRole('img', { name: /a scene|generated/i });
    fireEvent.click(thumb.closest('button') ?? thumb);
    fireEvent.click(await screen.findByRole('button', { name: 'Use as profile picture' }));
    // Nothing was written; the picker opened with that image already chosen.
    expect(setCharacterAvatar).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByTestId('picker-image-902').getAttribute('aria-pressed')).toBe('true'));
    expect(screen.queryByText('Set as avatar')).toBeNull();
  });

  it('a failed save is visible in the picker and the page keeps its current avatar', async () => {
    setCharacterAvatar.mockRejectedValue(new Error('This kind of image cannot be used as a character avatar.'));
    renderDetail();
    const section = await openManage();
    fireEvent.click(within(section).getByRole('button', { name: 'Change picture' }));
    fireEvent.click(await screen.findByTestId('picker-image-901'));
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Save profile picture' }));
    await within(dialog()).findByText('This kind of image cannot be used as a character avatar.');
    expect(updateCharacter).not.toHaveBeenCalled();
    const avatar = within(section).getByTestId('manage-avatar-preview').querySelector('img') as HTMLImageElement;
    expect(avatar.getAttribute('src')).toBe(WITH_MEDIA.avatar_url);
  });
});

describe('removing', () => {
  it('Remove picture confirms without a typed name, says the image is kept, and adopts the server response', async () => {
    removeCharacterAvatar.mockResolvedValue(FRESH);
    renderDetail();
    const section = await openManage();
    fireEvent.click(within(section).getByRole('button', { name: 'Remove picture' }));
    const d = dialog();
    expect(within(d).queryByLabelText(/to confirm/)).toBeNull();
    expect(d.textContent).toMatch(/not deleted — it stays in your image library/);
    fireEvent.click(within(d).getByRole('button', { name: 'Remove profile picture' }));

    await waitFor(() => expect(removeCharacterAvatar).toHaveBeenCalledWith(42));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(within(section).queryByRole('button', { name: 'Remove picture' })).toBeNull();
    expect(within(section).getByRole('button', { name: 'Choose picture' })).toBeTruthy();
    expect(within(section).getByTestId('manage-avatar-preview').querySelector('img')).toBeNull();
    await waitFor(() => expect(getMe).toHaveBeenCalledTimes(2)); // sidebar follows
  });

  it('Remove cover works the same way and does not touch the account', async () => {
    removeCharacterCover.mockResolvedValue({ ...WITH_MEDIA, cover_url: undefined, cover_position_x: 0.5, cover_position_y: 0.5 });
    renderDetail();
    const section = await openManage();
    fireEvent.click(within(section).getByRole('button', { name: 'Remove cover' }));
    expect(dialog().textContent).toMatch(/stays in your image library/);
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Remove cover' }));
    await waitFor(() => expect(removeCharacterCover).toHaveBeenCalledWith(42));
    await waitFor(() => expect(within(section).queryByRole('button', { name: 'Remove cover' })).toBeNull());
    expect(within(section).getByRole('button', { name: 'Choose cover' })).toBeTruthy();
    // The avatar side is untouched, and the account was not re-read.
    expect(within(section).getByRole('button', { name: 'Remove picture' })).toBeTruthy();
    expect(getMe).toHaveBeenCalledTimes(1);
  });

  it('a failed removal stays in the dialog with the error and changes nothing', async () => {
    removeCharacterAvatar.mockRejectedValue(new Error('Not authorized'));
    renderDetail();
    const section = await openManage();
    fireEvent.click(within(section).getByRole('button', { name: 'Remove picture' }));
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Remove profile picture' }));
    await waitFor(() => expect(within(dialog()).getByRole('alert').textContent).toContain('Not authorized'));
    expect(within(section).getByRole('button', { name: 'Remove picture' })).toBeTruthy();
    expect((within(section).getByTestId('manage-avatar-preview').querySelector('img') as HTMLImageElement).getAttribute('src')).toBe(WITH_MEDIA.avatar_url);
    expect(getMe).toHaveBeenCalledTimes(1);
  });
});

describe('cover — existing path still works', () => {
  it('Change cover saves through the cover route with framing and updates the page', async () => {
    const refreshed = { ...WITH_MEDIA, cover_url: GENERATED.url, cover_position_x: 0.5, cover_position_y: 0.5 };
    getCharacter.mockResolvedValueOnce(WITH_MEDIA).mockResolvedValueOnce(refreshed);
    renderDetail();
    const section = await openManage();
    fireEvent.click(within(section).getByRole('button', { name: 'Change cover' }));
    await waitFor(() => expect(listMyCharacterImages).toHaveBeenCalledWith(expect.objectContaining({ eligibleFor: 'cover' })));
    fireEvent.click(await screen.findByTestId('picker-image-902'));
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Set cover' }));
    await waitFor(() => expect(setCharacterCover).toHaveBeenCalledWith(42, 'character', 902, expect.any(Number), expect.any(Number)));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => {
      const cover = within(section).getByTestId('manage-cover-preview').querySelector('img') as HTMLImageElement;
      expect(cover.getAttribute('src')).toBe(GENERATED.url);
    });
    expect(getMe).toHaveBeenCalledTimes(1); // a cover is not on the sidebar
  });
});

describe('roster', () => {
  it('shows the canonical avatar with its framing, never portrait_url', async () => {
    useAuthStore.setState({ user: ME, status: 'authenticated' });
    getCharacters.mockResolvedValue([{ ...WITH_MEDIA, visual_locked: true, portrait_url: 'https://cdn.test/DEAD.png' }]);
    render(<MemoryRouter><Characters /></MemoryRouter>);
    const img = await screen.findByRole('img', { name: 'Taylor' });
    expect(img.getAttribute('src')).toBe(WITH_MEDIA.avatar_url);
    expect((img as HTMLImageElement).style.objectPosition).toBe('20% 80%');
    expect(document.querySelector('img[src*="DEAD"]')).toBeNull();
  });
});
