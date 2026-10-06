// @vitest-environment jsdom
/**
 * CharacterDetail shell + owner Manage surface — Polish Phase 5.6.
 *
 * The page's tabs and its owner Manage tab are one intentional beta surface:
 * Stories is gone until a character-scoped Stories product exists (PD-7);
 * the Manage tab reads Details → Profile picture & cover → Character images
 * → Identity Canon → Delete character, destructive last; the rendered tab is
 * derived from the tabs this viewer can see, so stale state (a hidden tab,
 * Manage held across an :id change to someone else's character) falls back
 * to Timeline instead of a blank page or a leaked panel; and ownership is
 * still `is_owner`, never an owner_id comparison.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character, User } from '@/lib/types';

const getCharacter = vi.fn();
const getMe = vi.fn();
const getCharacterMentions = vi.fn();
const getIdentityCanon = vi.fn();
const listCharacterImages = vi.fn();
const lockFaceCanon = vi.fn();
const lockBodyCanon = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    getCharacter: (...a: unknown[]) => getCharacter(...a),
    getMe: (...a: unknown[]) => getMe(...a),
    getCharacterMentions: (...a: unknown[]) => getCharacterMentions(...a),
    listCharacterImages: (...a: unknown[]) => listCharacterImages(...a),
    getCharacterPosts: () => Promise.resolve([]),
    listMyCharacterImages: () => Promise.resolve([]),
    getIdentityCanon: (...a: unknown[]) => getIdentityCanon(...a),
    lockFaceCanon: (...a: unknown[]) => lockFaceCanon(...a),
    lockBodyCanon: (...a: unknown[]) => lockBodyCanon(...a),
    hasToken: () => true,
  },
}));

import CharacterDetail from '@/pages/CharacterDetail';
import { useAuthStore } from '@/lib/store';
import characterDetailSource from '../CharacterDetail.tsx?raw';

const ORDINARY: User = {
  id: 7, email: 'me@test.invalid', username: 'me', character_count: 1,
  is_admin: false, is_seeder: false,
} as User;

const OWNED: Character = {
  id: 42, name: 'Taylor', species: 'human', visibility: 'public',
  short_bio: 'A detective.', avatar_url: '/a.png', cover_url: '/c.png',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  is_owner: true,
} as Character;

const SOMEONE_ELSES: Character = {
  ...OWNED, id: 43, name: 'Morgan', short_bio: 'A rival.', is_owner: false, owner_id: null,
} as Character;

function renderPage(id = 42) {
  return render(
    <MemoryRouter initialEntries={[`/characters/${id}`]}>
      {/* A way to change the :id without remounting the page element. */}
      <Link to="/characters/43">go to 43</Link>
      <Routes>
        <Route path="/characters/:id" element={<CharacterDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** The top-level tab strip, by accessible name, in DOM order. */
function tabLabels(): string[] {
  const timeline = screen.getByRole('button', { name: 'Timeline' });
  const strip = timeline.parentElement as HTMLElement;
  return within(strip).getAllByRole('button').map((b) => b.textContent?.trim() ?? '');
}

async function openManage() {
  await screen.findByRole('heading', { name: OWNED.name });
  fireEvent.click(await screen.findByRole('button', { name: 'Manage' }));
}

beforeEach(() => {
  vi.clearAllMocks();
  getCharacter.mockImplementation((id: number) =>
    Promise.resolve(id === 43 ? SOMEONE_ELSES : OWNED),
  );
  getMe.mockResolvedValue(ORDINARY);
  getCharacterMentions.mockResolvedValue([]);
  getIdentityCanon.mockResolvedValue(null);
  listCharacterImages.mockResolvedValue([]);
  useAuthStore.setState({ user: ORDINARY, status: 'authenticated' });
});

/** A canon as the server returns it, with the front images the lock routes require. */
function canonWith(flags: { face_locked: boolean; body_locked: boolean }) {
  return {
    id: 1, character_id: 42, status: flags.face_locked && flags.body_locked ? 'locked' : 'draft',
    face_canon: { face_front_image_url: '/f.png', face_description: null, locked: flags.face_locked },
    body_canon: { body_front_image_url: '/b.png', permanent_body_marks: [], locked: flags.body_locked },
    accessories: [], ...flags, updated_at: '2026-09-19T00:00:00Z', locked_at: null,
  };
}

afterEach(cleanup);

describe('Tabs', () => {
  it('an ordinary owner sees Timeline, Media, Tagged, Manage — and no Stories (PD-7)', async () => {
    renderPage();
    await screen.findByRole('button', { name: 'Manage' });
    expect(tabLabels()).toEqual(['Timeline', 'Media', 'Tagged', 'Manage']);
    expect(screen.queryByRole('button', { name: 'Stories' })).toBeNull();
    expect(screen.queryByText(/No Stories Yet/)).toBeNull();
  });

  it('a visitor sees Timeline, Media, Tagged — no Stories, no Manage', async () => {
    renderPage(43);
    await screen.findByRole('button', { name: 'Message' });
    expect(tabLabels()).toEqual(['Timeline', 'Media', 'Tagged']);
    expect(screen.queryByRole('button', { name: 'Stories' })).toBeNull();
  });

  it('the Stories panel no longer exists to be rendered, however state is forced (source-level pin)', () => {
    // Tab state is local and untyped by the URL, so there is no runtime
    // handle to force "stories" into it. The pin is structural instead: the
    // tab union has no such member and no branch renders the old placeholder,
    // so no stale value can resurrect it.
    expect(characterDetailSource).not.toMatch(/'stories'/);
    expect(characterDetailSource).not.toMatch(/No Stories Yet/);
    expect(characterDetailSource).not.toMatch(/Stories featuring/);
    // And the rendered tab is derived from the visible list, not read raw.
    expect(characterDetailSource).toMatch(/tabs\.some\(\(t\) => t\.id === activeTab\) \? activeTab : DEFAULT_TAB/);
  });

  it('a stale Manage selection falls back to Timeline on a character the viewer does not own', async () => {
    renderPage();
    await openManage();
    expect(screen.getByRole('region', { name: 'Delete character' })).toBeTruthy();
    // The bio is hidden on Manage; on the visitor page it must be back.
    expect(screen.queryByText('A detective.')).toBeNull();

    // Same page element, new :id → activeTab is still "manage" in state.
    fireEvent.click(screen.getByText('go to 43'));
    await screen.findByRole('heading', { name: 'Morgan' });
    await screen.findByRole('button', { name: 'Message' });

    // No Manage tab, no Manage content, and NOT a blank page: Timeline.
    expect(screen.queryByRole('button', { name: 'Manage' })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Delete character' })).toBeNull();
    expect(screen.queryByRole('region', { name: /Profile picture & cover/ })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Identity Canon' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Edit details' })).toBeNull();
    expect(screen.getByText('A rival.')).toBeTruthy();
    expect(screen.getByText(/hasn't posted yet/)).toBeTruthy();
    const timelineTab = screen.getByRole('button', { name: 'Timeline' });
    expect(timelineTab.className).toContain('border-gem');
  });

  it('an :id change closes owner-only overlays opened on the previous character', async () => {
    renderPage();
    await openManage();
    fireEvent.click(screen.getByRole('button', { name: 'Manage Character Canon' }));
    expect(screen.getByRole('heading', { name: 'Manage Character Canon' })).toBeTruthy();

    fireEvent.click(screen.getByText('go to 43'));
    await screen.findByRole('heading', { name: 'Morgan' });
    expect(screen.queryByRole('heading', { name: 'Manage Character Canon' })).toBeNull();
  });

  it('an :id change drops the previous character’s Tagged posts', async () => {
    getCharacterMentions.mockImplementation((id: number) =>
      Promise.resolve(id === 42
        ? [{ kind: 'post', created_at: '2026-01-02T00:00:00Z', payload: { content: 'about Taylor' } }]
        : []),
    );
    renderPage();
    await screen.findByRole('heading', { name: 'Taylor' });
    fireEvent.click(screen.getByRole('button', { name: 'Tagged' }));
    await screen.findByText('about Taylor');

    fireEvent.click(screen.getByText('go to 43'));
    await screen.findByRole('heading', { name: 'Morgan' });
    await waitFor(() => expect(screen.queryByText('about Taylor')).toBeNull());
    await screen.findByText(/Not Tagged Yet/);
    expect(getCharacterMentions).toHaveBeenLastCalledWith(43);
  });
});

describe('Owner Manage surface', () => {
  it('reads Details → Profile picture & cover → Character images → Identity Canon → Delete, in that order', async () => {
    renderPage();
    await openManage();
    const regions = screen.getAllByRole('region').map((r) => {
      const id = r.getAttribute('aria-labelledby');
      return id ? document.getElementById(id)?.textContent?.trim() : r.getAttribute('aria-label');
    });
    expect(regions).toEqual([
      'Details',
      'Profile picture & cover',
      'Character images',
      'Identity Canon',
      'Delete character',
    ]);
  });

  it('keeps the destructive action last and visibly apart', async () => {
    renderPage();
    await openManage();
    const regions = screen.getAllByRole('region');
    const last = regions[regions.length - 1];
    expect(last.getAttribute('aria-labelledby')).toBe('manage-delete-heading');
    expect(last.className).toMatch(/red/);
    expect(within(last).getByRole('button', { name: /Delete character/ })).toBeTruthy();
    // Nothing destructive lives in any other card.
    for (const r of regions.slice(0, -1)) {
      expect(within(r).queryByRole('button', { name: /Delete character/ })).toBeNull();
    }
  });

  it('carries no development-era grab-bag wording', async () => {
    renderPage();
    await openManage();
    expect(screen.queryByText('Character Tools')).toBeNull();
    expect(screen.queryByText('Danger Zone')).toBeNull();
    expect(screen.queryByText(/Set the avatar from any gallery image/)).toBeNull();
  });

  it('Edit Details and avatar/cover management remain reachable', async () => {
    renderPage();
    await openManage();
    expect(screen.getByRole('button', { name: 'Edit details' })).toBeTruthy();
    const media = screen.getByRole('region', { name: /Profile picture & cover/ });
    expect(within(media).getByRole('button', { name: 'Change picture' })).toBeTruthy();
    expect(within(media).getByRole('button', { name: 'Crop' })).toBeTruthy();
    expect(within(media).getByRole('button', { name: 'Remove picture' })).toBeTruthy();
    expect(within(media).getByRole('button', { name: 'Change cover' })).toBeTruthy();
    expect(within(media).getByRole('button', { name: 'Reposition' })).toBeTruthy();
    expect(within(media).getByRole('button', { name: 'Remove cover' })).toBeTruthy();
  });

  it('the Canon Manager launcher is offered to an ordinary owner, locked or not, and opens the manager', async () => {
    renderPage();
    await openManage();
    const canon = screen.getByRole('region', { name: 'Identity Canon' });
    expect(within(canon).getByText('In progress')).toBeTruthy();
    fireEvent.click(within(canon).getByRole('button', { name: 'Manage Character Canon' }));
    expect(screen.getByRole('heading', { name: 'Manage Character Canon' })).toBeTruthy();
  });

  it('Character images opens the Image Library on this character', async () => {
    let location = '';
    function Library() { location = window.location.pathname; return <p>LIBRARY</p>; }
    render(
      <MemoryRouter initialEntries={['/characters/42']}>
        <Routes>
          <Route path="/characters/:id" element={<CharacterDetail />} />
          <Route path="/images" element={<Library />} />
        </Routes>
      </MemoryRouter>,
    );
    await openManage();
    const images = screen.getByRole('region', { name: 'Character images' });
    fireEvent.click(within(images).getByRole('button', { name: 'Generate images' }));
    await screen.findByText('LIBRARY');
    void location;
  });

  it('shows no CTA to the 18+ Studio or any admin/founder-only destination', async () => {
    renderPage();
    await openManage();
    expect(screen.queryByText(/18\+/)).toBeNull();
    expect(screen.queryByText(/Studio/)).toBeNull();
    expect(screen.queryByText(/Admin/)).toBeNull();
    // Source-level: the page links nowhere gated above "creator".
    expect(characterDetailSource).not.toMatch(/studio\/18-plus|\/admin|adminCreator/);
  });
});

describe('Canon status — launcher and manager agree (Phase 5.7 addendum)', () => {
  it('abandoned pack: launcher and manager both say In progress; establishing flips both to Established', async () => {
    let locked = false;
    getCharacter.mockImplementation(() => Promise.resolve({ ...OWNED, has_identity_canon: true, visual_locked: locked }));
    getIdentityCanon.mockImplementation(() => Promise.resolve(canonWith({ face_locked: locked, body_locked: locked })));
    lockFaceCanon.mockResolvedValue({});
    lockBodyCanon.mockImplementation(() => { locked = true; return Promise.resolve({}); });

    renderPage();
    await openManage();
    const canonCard = screen.getByRole('region', { name: 'Identity Canon' });
    expect(within(canonCard).getByText('In progress')).toBeTruthy();
    fireEvent.click(within(canonCard).getByRole('button', { name: 'Manage Character Canon' }));
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByText('In progress');

    fireEvent.click(await within(dialog).findByRole('button', { name: 'Establish Character Canon' }));
    await within(dialog).findByText('Established');
    // The page re-read the character (a READ) and the launcher agrees.
    await waitFor(() => expect(within(canonCard).getByText('Established')).toBeTruthy());
    expect(lockFaceCanon).toHaveBeenCalledWith(42);
    expect(lockBodyCanon).toHaveBeenCalledWith(42);
    expect(getCharacter).toHaveBeenCalledTimes(2);
  });

  it('legacy character (visual_locked, no v2 canon): launcher and manager both say Needs attention, never Established', async () => {
    getCharacter.mockResolvedValue({ ...OWNED, visual_locked: true, has_identity_canon: false });
    getIdentityCanon.mockResolvedValue({
      id: 1, character_id: 42, status: 'draft', face_canon: null, body_canon: null, accessories: [],
      face_locked: false, body_locked: false, updated_at: '2026-09-19T00:00:00Z', locked_at: null,
    });
    renderPage();
    await openManage();
    const canonCard = screen.getByRole('region', { name: 'Identity Canon' });
    expect(within(canonCard).getByText('Needs attention')).toBeTruthy();
    fireEvent.click(within(canonCard).getByRole('button', { name: 'Manage Character Canon' }));
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByText('Needs attention');
    expect(screen.queryByText('Established')).toBeNull();
    expect(screen.queryByText('In progress')).toBeNull();
    expect(within(dialog).queryByRole('button', { name: 'Establish Character Canon' })).toBeNull();
  });

  it('established character: both say Established and no action is offered', async () => {
    getCharacter.mockResolvedValue({ ...OWNED, visual_locked: true, has_identity_canon: true });
    getIdentityCanon.mockResolvedValue(canonWith({ face_locked: true, body_locked: true }));
    renderPage();
    await openManage();
    const canonCard = screen.getByRole('region', { name: 'Identity Canon' });
    expect(within(canonCard).getByText('Established')).toBeTruthy();
    fireEvent.click(within(canonCard).getByRole('button', { name: 'Manage Character Canon' }));
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByText('Established');
    expect(within(dialog).queryByRole('button', { name: 'Establish Character Canon' })).toBeNull();
  });
});

describe('Dialogs on the page (Phase 5.8 accessibility)', () => {
  it('the Canon modal is a labelled dialog, takes focus, closes on Escape and returns focus to its launcher', async () => {
    renderPage();
    await openManage();
    const launcher = screen.getByRole('button', { name: 'Manage Character Canon' });
    fireEvent.click(launcher);
    const dialog = await screen.findByRole('dialog', { name: 'Manage Character Canon' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    await waitFor(() => expect(document.activeElement).toBe(dialog));
    fireEvent.keyDown(dialog, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Manage Character Canon' })).toBeNull());
    expect(document.activeElement).toBe(launcher);
  });

  it('the image preview is a labelled dialog with a named close button, closes on Escape, and closes on an :id change', async () => {
    listCharacterImages.mockImplementation((id: number) =>
      Promise.resolve(id === 42 ? [{ id: 9, url: '/nine.png', kind: 'scene_only' }] : []),
    );
    renderPage();
    await screen.findByRole('heading', { name: 'Taylor' });
    fireEvent.click(screen.getByRole('button', { name: 'Media' }));
    const thumb = await screen.findByRole('img', { name: 'Scene' });
    fireEvent.click(thumb.closest('button') ?? thumb);
    const preview = await screen.findByRole('dialog', { name: 'Image preview' });
    expect(within(preview).getByRole('button', { name: 'Close preview' })).toBeTruthy();
    fireEvent.keyDown(preview, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Image preview' })).toBeNull());

    // Re-open, then change character: the overlay must not survive.
    fireEvent.click(await screen.findByRole('img', { name: 'Scene' }));
    await screen.findByRole('dialog', { name: 'Image preview' });
    fireEvent.click(screen.getByText('go to 43'));
    await screen.findByRole('heading', { name: 'Morgan' });
    expect(screen.queryByRole('dialog', { name: 'Image preview' })).toBeNull();
  });
});

describe('Non-owner boundary', () => {
  it('a visitor gets no Manage tab, no management regions and no owner hero controls', async () => {
    renderPage(43);
    await screen.findByRole('button', { name: 'Message' });
    expect(screen.queryByRole('button', { name: 'Manage' })).toBeNull();
    expect(screen.queryAllByRole('region')).toHaveLength(0);
    expect(screen.queryByRole('button', { name: /change cover|add cover/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /profile picture/i })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Manage Character Canon' })).toBeNull();
    // The public view is intact: name, bio, tabs, Timeline empty state.
    expect(screen.getByRole('heading', { name: 'Morgan' })).toBeTruthy();
    expect(screen.getByText('A rival.')).toBeTruthy();
    expect(screen.getByText(/hasn't posted yet/)).toBeTruthy();
  });

  it('ownership is never decided by comparing owner_id (source-level pin)', () => {
    expect(characterDetailSource).toMatch(/character\.is_owner === true/);
    expect(characterDetailSource).not.toMatch(/owner_id\s*[=!]==?/);
    expect(characterDetailSource).not.toMatch(/[=!]==?\s*[\w.]*owner_id/);
  });
});
