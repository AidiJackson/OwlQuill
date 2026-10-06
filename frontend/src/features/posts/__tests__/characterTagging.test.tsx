// @vitest-environment jsdom
/**
 * W-10A — explicit character tagging, client side.
 *
 * * The "Tag characters" picker searches the PUBLIC-only mode, selects and
 *   removes, excludes the authoring character and stops at five.
 * * All three ordinary composers (Commons/WriteSpace on Home, the Realm New
 *   Post form, the character-page PostComposer) send `tagged_character_ids`.
 * * "Tagged: …" renders apart from the author byline and never says "with".
 * * The Tagged tab offers the character's OWNER a confirmed "Remove tag" for
 *   that character only; visitors get no such control.
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
import { useAuthStore } from '@/lib/store';

const ME = { id: 7, email: 'me@test.invalid', username: 'me', character_count: 2 } as User;
const PAN = { id: 42, name: 'Pan', owner_id: 7 };
const SHADOW = { id: 43, name: 'Shadow', owner_id: 7 };
const ELOWEN: CharacterSearchResult = { id: 90, name: 'Elowen' };
const COMMONS = { id: 1, name: 'Commons', slug: 'commons', is_public: true, is_commons: true, owner_id: 1 };
const HARBOUR = { id: 9, name: 'Harbour', slug: 'harbour', is_public: true, is_commons: false, owner_id: 1, is_member: true };

const pickerInput = () => screen.getByLabelText('Tag characters') as HTMLInputElement;

async function tagElowen() {
  fireEvent.change(pickerInput(), { target: { value: 'El' } });
  fireEvent.click(await screen.findByRole('button', { name: 'Tag Elowen' }));
  expect(screen.getByRole('button', { name: 'Remove Elowen' })).toBeTruthy();
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

describe('CharacterTagPicker', () => {
  it('searches the PUBLIC-only mode and never the generic search', async () => {
    renderPicker();
    expect(screen.getByText('Tag characters')).toBeTruthy();
    fireEvent.change(pickerInput(), { target: { value: 'El' } });
    await screen.findByRole('button', { name: 'Tag Elowen' });
    expect(searchTaggableCharacters).toHaveBeenCalledWith('El');
    expect(searchCharacters).not.toHaveBeenCalled();
  });

  it('does not search for fewer than two characters', async () => {
    renderPicker();
    fireEvent.change(pickerInput(), { target: { value: 'E' } });
    await new Promise((r) => setTimeout(r, 350));
    expect(searchTaggableCharacters).not.toHaveBeenCalled();
  });

  it('selects a result and lets it be removed before posting', async () => {
    const { onChange, rerender } = renderPicker();
    fireEvent.change(pickerInput(), { target: { value: 'El' } });
    fireEvent.click(await screen.findByRole('button', { name: 'Tag Elowen' }));
    expect(onChange).toHaveBeenLastCalledWith([{ character_id: 90, name: 'Elowen' }]);

    rerender([{ character_id: 90, name: 'Elowen' }]);
    fireEvent.click(screen.getByRole('button', { name: 'Remove Elowen' }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it('leaves the authoring character out of results and drops it from the selection', async () => {
    const { onChange } = renderPicker({ exclude: [PAN.id], selected: [{ character_id: PAN.id, name: 'Pan' }] });
    expect(onChange).toHaveBeenCalledWith([]);
    fireEvent.change(pickerInput(), { target: { value: 'an' } });
    await screen.findByRole('button', { name: 'Tag Elowen' });
    expect(screen.queryByRole('button', { name: 'Tag Pan' })).toBeNull();
  });

  it('stops at five', () => {
    const five = [1, 2, 3, 4, 5].map((i) => ({ character_id: i, name: `C${i}` }));
    renderPicker({ selected: five });
    expect(pickerInput().disabled).toBe(true);
    expect(screen.getByText('You can tag up to 5 characters.')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: /^Remove C/ })).toHaveLength(5);
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

describe('composers send tagged_character_ids', () => {
  it('Commons (Home)', async () => {
    renderAt('/', '/', <Home />);
    await screen.findByLabelText('Write a post');
    fireEvent.change(await screen.findByDisplayValue('— select character —'), { target: { value: String(PAN.id) } });
    fireEvent.change(screen.getByLabelText('Write a post'), { target: { value: 'At the docks.' } });
    await tagElowen();
    fireEvent.click(screen.getByRole('button', { name: 'Post' }));
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    expect(createPost.mock.calls[0][1]).toMatchObject({ character_id: PAN.id, tagged_character_ids: [ELOWEN.id] });
    // cleared after posting
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Remove Elowen' })).toBeNull());
  });

  it('Commons (Home) sends no tag field when nothing is tagged', async () => {
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
    await tagElowen();
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
    fireEvent.change(pickerInput(), { target: { value: 'an' } });
    await screen.findByRole('button', { name: 'Tag Elowen' });
    // The author is never offered to itself.
    expect(screen.queryByRole('button', { name: 'Tag Pan' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Tag Elowen' }));
    const post = screen.getByRole('button', { name: 'Post' });
    await waitFor(() => expect(post).toHaveProperty('disabled', false));
    fireEvent.click(post);
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    expect(createPost.mock.calls[0][0]).toBe(COMMONS.id);
    expect(createPost.mock.calls[0][1]).toMatchObject({ character_id: PAN.id, tagged_character_ids: [ELOWEN.id] });
  });
});

// ── presentation ─────────────────────────────────────────────────────────────

describe('TaggedCharacters', () => {
  it('renders "Tagged:" with links, never "with", and nothing when empty', () => {
    const { container, rerender } = render(
      <MemoryRouter>
        <TaggedCharacters postId={5} tags={[{ character_id: 90, name: 'Elowen' }, { character_id: 91, name: 'Leonardo Baptiste' }]} />
      </MemoryRouter>,
    );
    const line = screen.getByTestId('tagged-characters');
    expect(line.textContent).toBe('Tagged: Elowen, Leonardo Baptiste');
    expect(line.textContent).not.toMatch(/\bwith\b/i);
    expect(within(line).getByRole('link', { name: 'Leonardo Baptiste' }).getAttribute('href')).toBe('/characters/91');
    expect(screen.queryByRole('button', { name: /Remove tag/ })).toBeNull();

    rerender(<MemoryRouter><TaggedCharacters postId={5} tags={[]} /></MemoryRouter>);
    expect(container.textContent).toBe('');
  });

  it('offers a confirmed Remove tag only for the removable character', async () => {
    const onRemoved = vi.fn();
    render(
      <MemoryRouter>
        <TaggedCharacters
          postId={5}
          tags={[{ character_id: 90, name: 'Elowen' }, { character_id: 91, name: 'Leo' }]}
          removableCharacterId={90}
          onRemoved={onRemoved}
        />
      </MemoryRouter>,
    );
    expect(screen.getAllByRole('button', { name: /Remove tag/ })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Remove tag of Elowen from this post' }));
    const dialog = screen.getByRole('dialog');
    expect(removePostTag).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Remove tag' }));
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

describe('tags never change the author byline', () => {
  it('Commons feed', async () => {
    overrides.getFeed = () => Promise.resolve([otherPost()]);
    renderAt('/', '/', <Home />);
    const body = await screen.findByText('Bram at the docks.');
    const card = body.closest('article') ?? (body.parentElement?.parentElement as HTMLElement);
    const line = within(card).getByTestId('tagged-characters');
    expect(line.textContent).toBe('Tagged: Elowen');
    // Elowen appears ONLY in the Tagged line; Bram is the byline.
    expect(within(card).getAllByText('Elowen')).toHaveLength(1);
    expect(line.contains(within(card).getByText('Elowen'))).toBe(true);
    expect(within(card).getAllByText('Bram').some((el) => !line.contains(el))).toBe(true);
  });
});

// ── the Tagged tab ───────────────────────────────────────────────────────────

const ELOWEN_PAGE = {
  id: 90, name: 'Elowen', species: 'human', visibility: 'public', is_owner: true,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
};
const item = (p: Post) => ({
  type: 'post' as const, created_at: p.created_at, realm_id: p.realm_id, realm_name: 'Harbour',
  payload: p as unknown as Record<string, unknown>,
});

describe('Tagged tab', () => {
  it('is labelled Tagged and explains itself when empty', async () => {
    overrides.getCharacter = () => Promise.resolve(ELOWEN_PAGE);
    renderAt('/characters/90', '/characters/:id', <CharacterDetail />);
    fireEvent.click(await screen.findByRole('button', { name: 'Tagged' }));
    expect(await screen.findByText('Not Tagged Yet')).toBeTruthy();
    expect(screen.getByText('Posts where another character tags Elowen will appear here.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Mentions' })).toBeNull();
  });

  it('lets the owner remove THIS character’s tag, and the post leaves the list', async () => {
    overrides.getCharacter = () => Promise.resolve(ELOWEN_PAGE);
    overrides.getCharacterMentions = () =>
      Promise.resolve([item(otherPost({
        tagged_characters: [{ character_id: 90, name: 'Elowen' }, { character_id: 91, name: 'Leo' }],
      }))]);
    renderAt('/characters/90', '/characters/:id', <CharacterDetail />);
    fireEvent.click(await screen.findByRole('button', { name: 'Tagged' }));
    await screen.findByText('Bram at the docks.');

    const removes = screen.getAllByRole('button', { name: /Remove tag/ });
    expect(removes).toHaveLength(1);
    fireEvent.click(removes[0]);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove tag' }));
    await waitFor(() => expect(removePostTag).toHaveBeenCalledWith(60, 90));
    await waitFor(() => expect(screen.queryByText('Bram at the docks.')).toBeNull());
  });

  it('gives a visitor no Remove tag control', async () => {
    overrides.getCharacter = () => Promise.resolve({ ...ELOWEN_PAGE, is_owner: false });
    overrides.getCharacterMentions = () => Promise.resolve([item(otherPost())]);
    renderAt('/characters/90', '/characters/:id', <CharacterDetail />);
    fireEvent.click(await screen.findByRole('button', { name: 'Tagged' }));
    await screen.findByText('Bram at the docks.');
    expect(screen.getByTestId('tagged-characters').textContent).toBe('Tagged: Elowen');
    expect(screen.queryByRole('button', { name: /Remove tag/ })).toBeNull();
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
