// @vitest-environment jsdom
/**
 * W-01 — posts on a character's Timeline and Featured tabs open their post.
 *
 * Each card carries ONE link to /posts/{id}, laid under the card rather than
 * wrapped around it, so the card's own controls — the Featuring line, Remove
 * from Featured, the post menu, mention links — are never nested inside a link
 * and keep their own behaviour. Everything the card showed before still shows.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Post, User } from '@/lib/types';

const { removePostTag, overrides } = vi.hoisted(() => ({
  removePostTag: vi.fn(),
  overrides: {} as Record<string, (...a: unknown[]) => unknown>,
}));

vi.mock('@/lib/apiClient', () => ({
  apiClient: new Proxy(
    {},
    {
      get: (_t, key: string) => {
        if (key === 'removePostTag') return removePostTag;
        if (key === 'hasToken') return () => true;
        if (key === 'then') return undefined;
        return (...a: unknown[]) => (overrides[key] ? overrides[key](...a) : Promise.resolve([]));
      },
    },
  ),
}));

import CharacterDetail from '@/pages/CharacterDetail';
import { useAuthStore } from '@/lib/store';

const ME = { id: 7, email: 'me@test.invalid', username: 'me', character_count: 1 } as User;

const ELOWEN_PAGE = {
  id: 90, name: 'Elowen', species: 'human', visibility: 'public', is_owner: true,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
};

const post = (over: Partial<Post> = {}): Post =>
  ({
    id: 61, realm_id: 9, author_user_id: 7, character_id: 90, character_name: 'Elowen',
    title: null, content: 'Elowen watched the ships.', content_type: 'ic', post_kind: 'general',
    provenance: 'user_written', created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z',
    mentions: [], comment_count: 0, tagged_characters: [],
    ...over,
  }) as unknown as Post;

/** Someone else's post featuring Elowen. */
const featuring = (over: Partial<Post> = {}): Post =>
  post({
    id: 60, author_user_id: undefined, character_id: 3, character_name: 'Bram',
    content: 'Bram at the docks.', tagged_characters: [{ character_id: 90, name: 'Elowen' }],
    ...over,
  });

const item = (p: Post) => ({
  type: 'post' as const, created_at: p.created_at, realm_id: p.realm_id, realm_name: 'Harbour',
  payload: p as unknown as Record<string, unknown>,
});

function PostPage() {
  const { postId } = useParams();
  return <p>POST PAGE {postId}</p>;
}

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={['/characters/90']}>
      <Routes>
        <Route path="/characters/:id" element={<CharacterDetail />} />
        <Route path="/posts/:postId" element={<PostPage />} />
        <Route path="/characters/:id/*" element={<p>CHARACTER PAGE</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

/** The card a piece of text belongs to. */
const cardOf = (el: HTMLElement) => el.closest('article') as HTMLElement;

/** No link or button inside another link anywhere in the card. */
function expectNoNestedInteractives(card: HTMLElement) {
  for (const el of Array.from(card.querySelectorAll('a, button'))) {
    expect(el.parentElement?.closest('a')).toBeNull();
  }
}

beforeEach(() => {
  for (const k of Object.keys(overrides)) delete overrides[k];
  overrides.getCharacter = () => Promise.resolve(ELOWEN_PAGE);
  overrides.getMe = () => Promise.resolve(ME);
  removePostTag.mockReset().mockResolvedValue(undefined);
  Element.prototype.scrollIntoView = vi.fn();
  useAuthStore.setState({ user: ME });
});

afterEach(() => {
  cleanup();
  useAuthStore.setState({ user: null });
});

describe('Timeline posts', () => {
  it('each card has exactly one link, to its own post, and following it opens that post', async () => {
    overrides.getCharacterPosts = () =>
      Promise.resolve([item(post()), item(post({ id: 62, content: 'A second entry.' }))]);
    renderDetail();
    const card = cardOf(await screen.findByText('Elowen watched the ships.'));

    const links = within(card).getAllByRole('link', { name: /^Open post/ });
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute('href')).toBe('/posts/61');
    expect(links[0].getAttribute('aria-label')).toBe('Open post by Elowen');
    expect(within(cardOf(screen.getByText('A second entry.'))).getByTestId('post-card-link').getAttribute('href'))
      .toBe('/posts/62');

    fireEvent.click(links[0]);
    expect(await screen.findByText('POST PAGE 61')).toBeTruthy();
  });

  it('names a titled post by its title', async () => {
    overrides.getCharacterPosts = () => Promise.resolve([item(post({ title: 'The Harbour at Dusk' }))]);
    renderDetail();
    expect(await screen.findByRole('link', { name: 'Open post: The Harbour at Dusk' })).toBeTruthy();
    expect(screen.getByText('The Harbour at Dusk')).toBeTruthy();
  });

  it("the author's post menu does not navigate", async () => {
    overrides.getCharacterPosts = () => Promise.resolve([item(post())]);
    renderDetail();
    const card = cardOf(await screen.findByText('Elowen watched the ships.'));
    fireEvent.click(within(card).getByRole('button', { name: 'Post options' }));
    expect(screen.queryByText(/POST PAGE/)).toBeNull();
    expect(screen.getByText('Elowen watched the ships.')).toBeTruthy();
  });

  it('keeps the card as it was, with no nested interactive elements', async () => {
    overrides.getCharacterPosts = () => Promise.resolve([item(post({
      tagged_characters: [{ character_id: 91, name: 'Leo' }],
      image_url: '/static/generated/x.png',
    }))]);
    renderDetail();
    const body = await screen.findByText('Elowen watched the ships.');
    const card = cardOf(body);
    expect(within(card).getAllByText('Elowen').length).toBeGreaterThan(0); // byline
    expect(within(card).getByTestId('tagged-characters').textContent).toBe('Featuring Leo');
    expect(within(card).getByText('Oct 2')).toBeTruthy();
    expect(within(card).getByRole('img', { name: 'Post image' })).toBeTruthy();
    expectNoNestedInteractives(card);
    // The link is empty: it wraps nothing, so it cannot swallow other controls.
    expect(within(card).getByTestId('post-card-link').childElementCount).toBe(0);
  });

  it('a timeline item that is not a post gets no link', async () => {
    overrides.getCharacterPosts = () =>
      Promise.resolve([{ type: 'scene', created_at: '2026-10-02T00:00:00Z', payload: { content: 'Not a post.' } }]);
    renderDetail();
    const card = cardOf(await screen.findByText('Not a post.'));
    expect(within(card).queryByTestId('post-card-link')).toBeNull();
  });
});

describe('Featured posts', () => {
  async function openFeatured(items: ReturnType<typeof item>[], isOwner = true) {
    overrides.getCharacter = () => Promise.resolve({ ...ELOWEN_PAGE, is_owner: isOwner });
    overrides.getCharacterMentions = () => Promise.resolve(items);
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Featured' }));
    return cardOf(await screen.findByText('Bram at the docks.'));
  }

  it("each card links to the featuring post, attributed to its author, and opens it", async () => {
    const card = await openFeatured([item(featuring())], false);
    const link = within(card).getByRole('link', { name: 'Open post by Bram' });
    expect(link.getAttribute('href')).toBe('/posts/60');
    expect(within(card).getAllByRole('link', { name: /^Open post/ })).toHaveLength(1);
    expectNoNestedInteractives(card);

    fireEvent.click(link);
    expect(await screen.findByText('POST PAGE 60')).toBeTruthy();
  });

  it('Remove from Featured still works and never navigates', async () => {
    const card = await openFeatured([item(featuring())]);
    fireEvent.click(within(card).getByRole('button', { name: 'Remove Elowen from Featured on this post' }));
    expect(screen.queryByText(/POST PAGE/)).toBeNull();

    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove from Featured' }));
    await waitFor(() => expect(removePostTag).toHaveBeenCalledWith(60, 90));
    await waitFor(() => expect(screen.queryByText('Bram at the docks.')).toBeNull());
    expect(screen.queryByText(/POST PAGE/)).toBeNull();
  });

  it('Featured stays separate from the Timeline', async () => {
    overrides.getCharacterPosts = () => Promise.resolve([item(post())]);
    const card = await openFeatured([item(featuring())]);
    expect(screen.queryByText('Elowen watched the ships.')).toBeNull();
    expect(within(card).getByTestId('tagged-characters').textContent).toBe('Featuring Elowen');
  });
});
