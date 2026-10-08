// @vitest-environment jsdom
/**
 * W-10A — explicit character tagging, client side.
 *
 * * The compact "Featuring" picker ("+ Add characters") searches the
 *   PUBLIC-only mode, selects and removes chips, excludes the authoring
 *   character and stops at five.
 * * All three ordinary composers (Commons/WriteSpace on Home, the Realm New
 *   Post form, the character-page PostComposer) send `tagged_character_ids`.
 * * "Featuring …" renders in the post HEADER's secondary line (with the
 *   realm context), before the body, apart from the author byline, never
 *   "with", and never as a body-level "Tagged:" line. Four or more collapse
 *   to two names plus an accessible "+N".
 * * The Featured tab offers the character's OWNER a confirmed "Remove from
 *   Featured" for that character only; visitors get no such control.
 *
 * The server is the authority on every rule; these pin what the client sends
 * and shows.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CharacterSearchResult, Post, TaggedCharacter, User } from '@/lib/types';

const { createPost, searchTaggableCharacters, searchCharacters, removePostTag, overrides } = vi.hoisted(() => ({
  createPost: vi.fn(),
  searchTaggableCharacters: vi.fn(),
  searchCharacters: vi.fn(),
  removePostTag: vi.fn(),
  overrides: {} as Record<string, (...a: unknown[]) => unknown>,
}));

vi.mock('@/lib/apiClient', () => ({
  apiClient: new Proxy(
    {},
    {
      get: (_t, key: string) => {
        const named: Record<string, unknown> = {
          createPost, searchTaggableCharacters, searchCharacters, removePostTag,
        };
        if (key in named) return named[key];
        if (key === 'hasToken') return () => true;
        if (key === 'then') return undefined;
        return (...a: unknown[]) => (overrides[key] ? overrides[key](...a) : Promise.resolve([]));
      },
    },
  ),
}));

import CharacterTagPicker from '@/features/posts/components/CharacterTagPicker';
import TaggedCharacters from '@/features/posts/components/TaggedCharacters';
import PostComposer from '@/features/posts/components/PostComposer';
import { afterTagRemoved } from '@/features/posts/taggedSurface';
import Home from '@/pages/Home';
import RealmDetail from '@/pages/RealmDetail';
import CharacterDetail from '@/pages/CharacterDetail';
import PostDetail from '@/pages/PostDetail';
import { useAuthStore } from '@/lib/store';

const ME = { id: 7, email: 'me@test.invalid', username: 'me', character_count: 2 } as User;
const PAN = { id: 42, name: 'Pan', owner_id: 7 };
const SHADOW = { id: 43, name: 'Shadow', owner_id: 7 };
const ELOWEN: CharacterSearchResult = { id: 90, name: 'Elowen' };
const COMMONS = { id: 1, name: 'Commons', slug: 'commons', is_public: true, is_commons: true, owner_id: 1 };
const HARBOUR = { id: 9, name: 'Harbour', slug: 'harbour', is_public: true, is_commons: false, owner_id: 1, is_member: true };

const openPicker = () => fireEvent.click(screen.getByRole('button', { name: 'Add featured characters' }));
const pickerInput = () => screen.getByRole('searchbox', { name: 'Add featured characters' }) as HTMLInputElement;

async function featureElowen() {
  openPicker();
  fireEvent.change(pickerInput(), { target: { value: 'El' } });
  fireEvent.click(await screen.findByRole('button', { name: 'Feature Elowen' }));
  expect(screen.getByRole('button', { name: 'Remove Elowen from Featuring' })).toBeTruthy();
}

beforeEach(() => {
  for (const k of Object.keys(overrides)) delete overrides[k];
  overrides.getRealms = () => Promise.resolve([COMMONS, HARBOUR]);
  overrides.getRealm = () => Promise.resolve(HARBOUR);
  overrides.getCharacters = () => Promise.resolve([PAN, SHADOW]);
  overrides.createCompositionSession = () => Promise.resolve({ id: 'sess', status: 'open' });
  overrides.updateCompositionSession = () => Promise.resolve({ id: 'sess', status: 'open' });
  createPost.mockReset().mockImplementation((_realm: number, p: { content: string }) =>
    Promise.resolve({ id: 777, content: p.content, created_at: '2026-10-06T00:00:00Z', mentions: [], tagged_characters: [] }),
  );
  // PAN is the caller's own PUBLIC character: offered unless it is the author.
  searchTaggableCharacters.mockReset().mockResolvedValue([PAN, ELOWEN]);
  searchCharacters.mockReset().mockResolvedValue([]);
  removePostTag.mockReset().mockResolvedValue(undefined);
  useAuthStore.setState({ user: ME });
});

afterEach(() => {
  cleanup();
  useAuthStore.setState({ user: null });
});

// ── the picker ───────────────────────────────────────────────────────────────

function renderPicker(props: { selected?: TaggedCharacter[]; exclude?: number[] } = {}) {
  const onChange = vi.fn();
  const view = (selected: TaggedCharacter[]) => (
    <CharacterTagPicker selected={selected} onChange={onChange} excludeCharacterIds={props.exclude ?? []} />
  );
  const utils = render(view(props.selected ?? []));
  return { onChange, rerender: (s: TaggedCharacter[]) => utils.rerender(view(s)) };
}

describe('CharacterTagPicker (Featuring)', () => {
  it('is a compact "Featuring  + Add characters" row until opened', () => {
    renderPicker();
    const group = screen.getByRole('group', { name: 'Featured characters' });
    expect(within(group).getByText('Featuring')).toBeTruthy();
    expect(within(group).getByRole('button', { name: 'Add featured characters' }).textContent).toBe('Add characters');
    expect(screen.queryByRole('searchbox')).toBeNull();
    expect(screen.queryByText(/Tag characters/)).toBeNull();
  });

  it('searches the PUBLIC-only mode and never the generic search', async () => {
    renderPicker();
    openPicker();
    expect(document.activeElement).toBe(pickerInput());
    fireEvent.change(pickerInput(), { target: { value: 'El' } });
    await screen.findByRole('button', { name: 'Feature Elowen' });
    expect(searchTaggableCharacters).toHaveBeenCalledWith('El');
    expect(searchCharacters).not.toHaveBeenCalled();
  });

  it('does not search for fewer than two characters', async () => {
    renderPicker();
    openPicker();
    fireEvent.change(pickerInput(), { target: { value: 'E' } });
    await new Promise((r) => setTimeout(r, 350));
    expect(searchTaggableCharacters).not.toHaveBeenCalled();
  });

  it('selects a result as a removable chip, then offers a shorter "+ Add"', async () => {
    const { onChange, rerender } = renderPicker();
    openPicker();
    fireEvent.change(pickerInput(), { target: { value: 'El' } });
    fireEvent.click(await screen.findByRole('button', { name: 'Feature Elowen' }));
    expect(onChange).toHaveBeenLastCalledWith([{ character_id: 90, name: 'Elowen' }]);
    // the search closes after a pick
    expect(screen.queryByRole('searchbox')).toBeNull();

    rerender([{ character_id: 90, name: 'Elowen' }]);
    const group = screen.getByRole('group', { name: 'Featured characters' });
    expect(within(group).getByText('Elowen')).toBeTruthy();
    expect(within(group).getByRole('button', { name: 'Add featured characters' }).textContent).toBe('Add');
    fireEvent.click(screen.getByRole('button', { name: 'Remove Elowen from Featuring' }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it('Escape closes the search without selecting', async () => {
    const { onChange } = renderPicker();
    openPicker();
    fireEvent.change(pickerInput(), { target: { value: 'El' } });
    fireEvent.keyDown(pickerInput(), { key: 'Escape' });
    expect(screen.queryByRole('searchbox')).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it('leaves the authoring character out of results and drops it from the selection', async () => {
    const { onChange } = renderPicker({ exclude: [PAN.id], selected: [{ character_id: PAN.id, name: 'Pan' }] });
    expect(onChange).toHaveBeenCalledWith([]);
    openPicker();
    fireEvent.change(pickerInput(), { target: { value: 'an' } });
    await screen.findByRole('button', { name: 'Feature Elowen' });
    expect(screen.queryByRole('button', { name: 'Feature Pan' })).toBeNull();
  });

  it('stops at five', () => {
    const five = [1, 2, 3, 4, 5].map((i) => ({ character_id: i, name: `C${i}` }));
    renderPicker({ selected: five });
    expect(screen.queryByRole('button', { name: 'Add featured characters' })).toBeNull();
    expect(screen.getByText('Up to 5')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: /^Remove C\d from Featuring$/ })).toHaveLength(5);
  });
});

// ── the three composers ──────────────────────────────────────────────────────

const renderAt = (path: string, route: string, element: JSX.Element) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={route} element={element} />
      </Routes>
    </MemoryRouter>,
  );

describe('composers send tagged_character_ids (Featuring)', () => {
  it('Commons (Home)', async () => {
    renderAt('/', '/', <Home />);
    await screen.findByLabelText('Write a post');
    fireEvent.change(await screen.findByDisplayValue('— select character —'), { target: { value: String(PAN.id) } });
    fireEvent.change(screen.getByLabelText('Write a post'), { target: { value: 'At the docks.' } });
    await featureElowen();
    fireEvent.click(screen.getByRole('button', { name: 'Post' }));
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    expect(createPost.mock.calls[0][1]).toMatchObject({ character_id: PAN.id, tagged_character_ids: [ELOWEN.id] });
    // cleared after posting
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Remove Elowen from Featuring' })).toBeNull());
  });

  it('Commons (Home) sends no tag field when nobody is featured', async () => {
    renderAt('/', '/', <Home />);
    await screen.findByLabelText('Write a post');
    fireEvent.change(await screen.findByDisplayValue('— select character —'), { target: { value: String(PAN.id) } });
    fireEvent.change(screen.getByLabelText('Write a post'), { target: { value: 'Alone.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Post' }));
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    expect(createPost.mock.calls[0][1]).not.toHaveProperty('tagged_character_ids');
  });

  it('Realm New Post', async () => {
    renderAt(`/realms/${HARBOUR.id}`, '/realms/:realmId', <RealmDetail />);
    fireEvent.click(await screen.findByRole('button', { name: '+ New Post' }));
    fireEvent.change(await screen.findByDisplayValue('— select character —'), { target: { value: String(SHADOW.id) } });
    fireEvent.change(screen.getByLabelText('Post content'), { target: { value: 'A realm post.' } });
    await featureElowen();
    fireEvent.click(screen.getByRole('button', { name: 'Post' }));
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    expect(createPost.mock.calls[0][0]).toBe(HARBOUR.id);
    expect(createPost.mock.calls[0][1]).toMatchObject({ character_id: SHADOW.id, tagged_character_ids: [ELOWEN.id] });
  });

  it('character-page PostComposer', async () => {
    render(
      <MemoryRouter>
        <PostComposer open onClose={() => {}} characterId={PAN.id} characterName="Pan" />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByPlaceholderText("What's on your mind?"), { target: { value: 'From the gallery.' } });
    openPicker();
    fireEvent.change(pickerInput(), { target: { value: 'an' } });
    await screen.findByRole('button', { name: 'Feature Elowen' });
    // The author is never offered to itself.
    expect(screen.queryByRole('button', { name: 'Feature Pan' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Feature Elowen' }));
    const post = screen.getByRole('button', { name: 'Post' });
    await waitFor(() => expect(post).toHaveProperty('disabled', false));
    fireEvent.click(post);
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    expect(createPost.mock.calls[0][0]).toBe(COMMONS.id);
    expect(createPost.mock.calls[0][1]).toMatchObject({ character_id: PAN.id, tagged_character_ids: [ELOWEN.id] });
  });
});

// ── presentation ─────────────────────────────────────────────────────────────

const inRouter = (el: JSX.Element) => <MemoryRouter>{el}</MemoryRouter>;
const many = (n: number) =>
  Array.from({ length: n }, (_, i) => ({ character_id: 100 + i, name: `Name ${i + 1}` }));

describe('TaggedCharacters (Featuring line)', () => {
  it('renders "Featuring" with links, never "with" or "Tagged", then the context after a dot', () => {
    render(inRouter(
      <TaggedCharacters
        postId={5}
        tags={[{ character_id: 90, name: 'Elowen' }, { character_id: 91, name: 'Leonardo Baptiste' }]}
        context={<span>in The Commons</span>}
      />,
    ));
    const featuring = screen.getByTestId('tagged-characters');
    expect(featuring.textContent).toBe('Featuring Elowen, Leonardo Baptiste');
    expect(screen.getByTestId('post-context-line').textContent).toBe('Featuring Elowen, Leonardo Baptiste·in The Commons');
    expect(screen.getByTestId('post-context-line').textContent).not.toMatch(/\bwith\b|Tagged/i);
    expect(within(featuring).getByRole('link', { name: 'Leonardo Baptiste' }).getAttribute('href')).toBe('/characters/91');
    expect(screen.queryByRole('button', { name: /Remove/ })).toBeNull();
  });

  it('with nobody featured renders only the context, and with neither renders nothing', () => {
    const { container, rerender } = render(inRouter(<TaggedCharacters postId={5} tags={[]} context={<span>in Harbour</span>} />));
    expect(screen.getByTestId('post-context-line').textContent).toBe('in Harbour');
    expect(screen.queryByTestId('tagged-characters')).toBeNull();
    rerender(inRouter(<TaggedCharacters postId={5} tags={[]} />));
    expect(container.textContent).toBe('');
  });

  it('shows up to three in full', () => {
    render(inRouter(<TaggedCharacters postId={5} tags={many(3)} />));
    expect(screen.getByTestId('tagged-characters').textContent).toBe('Featuring Name 1, Name 2, Name 3');
    expect(screen.queryByRole('button', { name: /more featured/ })).toBeNull();
  });

  it('collapses four or more to two names and an accessible +N that expands in place', () => {
    render(inRouter(<TaggedCharacters postId={5} tags={many(4)} />));
    expect(screen.getByTestId('tagged-characters').textContent).toBe('Featuring Name 1, Name 2 +2');
    const more = screen.getByRole('button', { name: 'Show 2 more featured: Name 3, Name 4' });
    expect(more.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(more);
    expect(screen.getByTestId('tagged-characters').textContent).toBe('Featuring Name 1, Name 2, Name 3, Name 4');
    expect(screen.getAllByRole('link')).toHaveLength(4);
  });

  it('offers a confirmed "Remove from Featured" only for the removable character, listed first', async () => {
    const onRemoved = vi.fn();
    render(inRouter(
      <TaggedCharacters
        postId={5}
        tags={[...many(3), { character_id: 90, name: 'Elowen' }]}
        removableCharacterId={90}
        onRemoved={onRemoved}
      />,
    ));
    // Never collapsed away: the viewer's own character leads.
    expect(screen.getByTestId('tagged-characters').textContent).toBe('Featuring Elowen, Name 1 +2');
    expect(screen.getAllByRole('button', { name: /Remove/ })).toHaveLength(1);
    const action = screen.getByRole('button', { name: 'Remove Elowen from Featured on this post' });
    expect(action.textContent).toBe('Remove from Featured');
    fireEvent.click(action);
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Remove from Featured?')).toBeTruthy();
    expect(dialog.textContent).toMatch(/original post is not\s+deleted or edited/);
    expect(dialog.textContent).not.toMatch(/can't add it back/);
    expect(removePostTag).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Remove from Featured' }));
    await waitFor(() => expect(removePostTag).toHaveBeenCalledWith(5, 90));
    await waitFor(() => expect(onRemoved).toHaveBeenCalledWith(90));
  });
});

const otherPost = (over: Partial<Post> = {}): Post =>
  ({
    id: 60, realm_id: 9, author_user_id: undefined, character_id: 3, character_name: 'Bram',
    title: null, content: 'Bram at the docks.', content_type: 'ic', post_kind: 'general',
    provenance: 'user_written', created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
    mentions: [], comment_count: 0,
    tagged_characters: [{ character_id: 90, name: 'Elowen' }],
    ...over,
  }) as unknown as Post;

/** Featuring sits in the header — before the body — and never in the byline. */
function expectHeaderFeaturing(card: HTMLElement, body: HTMLElement) {
  const line = within(card).getByTestId('tagged-characters');
  expect(line.textContent).toBe('Featuring Elowen');
  // DOM order: the Featuring line precedes the post body.
  expect(line.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  // Elowen appears ONLY in the Featuring line; Bram is still the byline.
  expect(within(card).getAllByText('Elowen')).toHaveLength(1);
  expect(within(card).getAllByText('Bram').some((el) => !line.contains(el))).toBe(true);
  // No old body-level "Tagged:" line anywhere.
  expect(card.textContent).not.toMatch(/Tagged:/);
}

describe('Featuring is header metadata on every post surface', () => {
  it('Commons feed: "Featuring Elowen · in Commons"', async () => {
    overrides.getFeed = () => Promise.resolve([otherPost({ realm_id: COMMONS.id })]);
    renderAt('/', '/', <Home />);
    const body = await screen.findByText('Bram at the docks.');
    const card = body.closest('article') as HTMLElement;
    expectHeaderFeaturing(card, body);
    expect(within(card).getByTestId('post-context-line').textContent).toBe('Featuring Elowen·in Commons');
  });

  it('Realm feed', async () => {
    overrides.getRealmPosts = () => Promise.resolve([otherPost()]);
    renderAt(`/realms/${HARBOUR.id}`, '/realms/:realmId', <RealmDetail />);
    const body = await screen.findByText('Bram at the docks.');
    expectHeaderFeaturing(body.closest('.card') as HTMLElement, body);
  });

  it('Post detail', async () => {
    overrides.getPost = () => Promise.resolve(otherPost());
    renderAt('/posts/60', '/posts/:postId', <PostDetail />);
    const body = await screen.findByText('Bram at the docks.');
    const card = body.closest('article') as HTMLElement;
    expectHeaderFeaturing(card, body);
    expect(within(card).getByTestId('post-context-line').textContent).toBe('Featuring Elowen·in Harbour');
  });
});

// ── the Featured tab ─────────────────────────────────────────────────────────

const ELOWEN_PAGE = {
  id: 90, name: 'Elowen', species: 'human', visibility: 'public', is_owner: true,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
};
const item = (p: Post) => ({
  type: 'post' as const, created_at: p.created_at, realm_id: p.realm_id, realm_name: 'Harbour',
  payload: p as unknown as Record<string, unknown>,
});

describe('Featured tab', () => {
  it('is labelled Featured and explains itself when empty', async () => {
    overrides.getCharacter = () => Promise.resolve(ELOWEN_PAGE);
    renderAt('/characters/90', '/characters/:id', <CharacterDetail />);
    fireEvent.click(await screen.findByRole('button', { name: 'Featured' }));
    expect(await screen.findByText('Not Featured Yet')).toBeTruthy();
    expect(screen.getByText('Posts where other characters feature Elowen will appear here.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Tagged' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Mentions' })).toBeNull();
  });

  it('shows Featuring in the card header with the realm, before the body', async () => {
    overrides.getCharacter = () => Promise.resolve({ ...ELOWEN_PAGE, is_owner: false });
    overrides.getCharacterMentions = () => Promise.resolve([item(otherPost())]);
    renderAt('/characters/90', '/characters/:id', <CharacterDetail />);
    fireEvent.click(await screen.findByRole('button', { name: 'Featured' }));
    const body = await screen.findByText('Bram at the docks.');
    const card = body.closest('article') as HTMLElement;
    expect(within(card).getByTestId('post-context-line').textContent).toBe('Featuring Elowen·in Harbour');
    expect(within(card).getByTestId('tagged-characters').compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('lets the owner remove THIS character from Featured, and the post leaves the list', async () => {
    overrides.getCharacter = () => Promise.resolve(ELOWEN_PAGE);
    overrides.getCharacterMentions = () =>
      Promise.resolve([item(otherPost({
        tagged_characters: [{ character_id: 91, name: 'Leo' }, { character_id: 90, name: 'Elowen' }],
      }))]);
    renderAt('/characters/90', '/characters/:id', <CharacterDetail />);
    fireEvent.click(await screen.findByRole('button', { name: 'Featured' }));
    await screen.findByText('Bram at the docks.');

    const removes = screen.getAllByRole('button', { name: /from Featured on this post/ });
    expect(removes).toHaveLength(1);
    fireEvent.click(removes[0]);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove from Featured' }));
    await waitFor(() => expect(removePostTag).toHaveBeenCalledWith(60, 90));
    await waitFor(() => expect(screen.queryByText('Bram at the docks.')).toBeNull());
  });

  it('gives a visitor no Remove from Featured control', async () => {
    overrides.getCharacter = () => Promise.resolve({ ...ELOWEN_PAGE, is_owner: false });
    overrides.getCharacterMentions = () => Promise.resolve([item(otherPost())]);
    renderAt('/characters/90', '/characters/:id', <CharacterDetail />);
    fireEvent.click(await screen.findByRole('button', { name: 'Featured' }));
    await screen.findByText('Bram at the docks.');
    expect(screen.getByTestId('tagged-characters').textContent).toBe('Featuring Elowen');
    expect(screen.queryByRole('button', { name: /Remove/ })).toBeNull();
  });
});

describe('afterTagRemoved', () => {
  const tagged = item(otherPost({ id: 1 }));
  const alsoMentioned = item(otherPost({
    id: 2,
    mentions: [{ mention_text: '@Elowen', target_type: 'character', target_id: 90, display_name: 'Elowen', url: '/characters/90' }],
  }));
  const unrelated = item(otherPost({ id: 3 }));

  it('drops a post associated only by the removed tag', () => {
    expect(afterTagRemoved([tagged, unrelated], 1, 90).map((i) => (i.payload as { id: number }).id)).toEqual([3]);
  });

  it('keeps a post a legacy mention still associates, without the tag', () => {
    const [kept] = afterTagRemoved([alsoMentioned], 2, 90);
    expect((kept.payload as { tagged_characters: TaggedCharacter[] }).tagged_characters).toEqual([]);
  });
});
