// @vitest-environment jsdom
/**
 * The destination half of WriteSpace's Continue to publish.
 *
 * WriteSpace writes a finalisation record and navigates; the Commons composer
 * (Home) or the targeted Realm's New Post form prefills itself from it, adopts
 * the draft's composition session with `CompositionTracker.resume()`, and lets
 * the writer choose the final details before Post creates the post through the
 * canonical endpoint.
 *
 * Provenance verdicts are the server's (backend/tests/test_provenance.py pins
 * them). What is pinned here is what the client hands the server: which
 * session, and which counters — adopted from the server's own record, never
 * upgraded from the prefilled text.
 *
 * Also pins the character-first voice defaults: every composer that posts as a
 * character opens IC, with OOC one choice away.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { User } from '@/lib/types';

// Hoisted: the auth store reads apiClient while this file's imports evaluate.
const {
  createPost,
  getCompositionSession,
  createCompositionSession,
  updateCompositionSession,
  listMyCharacterImages,
  overrides,
} = vi.hoisted(() => ({
  createPost: vi.fn(),
  getCompositionSession: vi.fn(),
  createCompositionSession: vi.fn(),
  updateCompositionSession: vi.fn(),
  listMyCharacterImages: vi.fn(),
  overrides: {} as Record<string, (...a: unknown[]) => unknown>,
}));

vi.mock('@/lib/apiClient', () => ({
  apiClient: new Proxy(
    {},
    {
      get: (_t, key: string) => {
        const named: Record<string, unknown> = {
          createPost,
          getCompositionSession,
          createCompositionSession,
          updateCompositionSession,
          listMyCharacterImages,
        };
        if (key in named) return named[key];
        if (key === 'hasToken') return () => true;
        if (key === 'then') return undefined;
        return (...a: unknown[]) => (overrides[key] ? overrides[key](...a) : Promise.resolve([]));
      },
    },
  ),
}));

import Home from '@/pages/Home';
import RealmDetail from '@/pages/RealmDetail';
import PostComposer from '@/features/posts/components/PostComposer';
import { useAuthStore } from '@/lib/store';

const FINALISE_KEY = 'ficshon.writespace.finalise';
const COPY_HANDOFF_KEY = 'ficshon.composition.handoff';
const BODY_KEY = 'ficshon.workspace.body';
const TITLE_KEY = 'ficshon.workspace.title';
const SESSION_KEY = 'ficshon.writespace.composition_session_id';

const SESSION_ID = '11111111-2222-4333-8444-555555555555';
const DRAFT = 'Pan crossed the harbour at dusk, counting lanterns.\n\nThe tide came in behind him.';

const ME = { id: 7, email: 'me@test.invalid', username: 'me', character_count: 2 } as User;
const PAN = { id: 42, name: 'Pan', owner_id: 7 };
const SHADOW = { id: 43, name: 'Shadow', owner_id: 7 };
const COMMONS = { id: 1, name: 'Commons', slug: 'commons', is_public: true, is_commons: true, owner_id: 1 };
const HARBOUR = { id: 9, name: 'Harbour', slug: 'harbour', is_public: true, is_commons: false, owner_id: 1 };
const IMAGE = { id: 501, url: '/static/images/pan-dusk.png', kind: 'generated', prompt_summary: 'Pan at dusk' };

function LocationProbe() {
  return <div data-testid="location">{useLocation().pathname}</div>;
}
const location = () => screen.getByTestId('location').textContent;

function seedFinalisation(over: Record<string, unknown> = {}) {
  sessionStorage.setItem(
    FINALISE_KEY,
    JSON.stringify({
      v: 1,
      sessionId: SESSION_ID,
      characterId: PAN.id,
      contentType: 'ic',
      title: 'Lanterns',
      body: DRAFT,
      realmId: null,
      createdAt: Date.now(),
      ...over,
    }),
  );
}

function seedWriteSpaceDraft() {
  localStorage.setItem(BODY_KEY, DRAFT);
  localStorage.setItem(TITLE_KEY, 'Lanterns');
  localStorage.setItem(SESSION_KEY, SESSION_ID);
}

const record = () => JSON.parse(sessionStorage.getItem(FINALISE_KEY) ?? 'null');

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<><Home /><LocationProbe /></>} />
        <Route path="/realms/:realmId" element={<><RealmDetail /><LocationProbe /></>} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

const composer = () => screen.getByLabelText('Write a post') as HTMLTextAreaElement;
const voice = () => screen.getByLabelText('Writing mode') as HTMLSelectElement;
const postButton = () => screen.getByRole('button', { name: 'Post' });
const realmContent = () => screen.getByLabelText('Post content') as HTMLTextAreaElement;
const lastPatch = () => updateCompositionSession.mock.calls[updateCompositionSession.mock.calls.length - 1]?.[1];

async function mountHome() {
  renderAt('/');
  await screen.findByLabelText('Write a post');
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  for (const k of Object.keys(overrides)) delete overrides[k];
  overrides.getRealms = () => Promise.resolve([COMMONS, HARBOUR]);
  overrides.getCharacters = () => Promise.resolve([PAN, SHADOW]);
  overrides.getRealm = (id: unknown) =>
    Promise.resolve(Number(id) === HARBOUR.id ? HARBOUR : Number(id) === COMMONS.id ? COMMONS : { ...HARBOUR, id: Number(id), name: 'Elsewhere' });
  createPost.mockReset().mockImplementation((_realm: number, p: { content: string }) =>
    Promise.resolve({ id: 777, content: p.content, created_at: '2026-09-29T00:00:00Z', mentions: [] }),
  );
  getCompositionSession.mockReset().mockResolvedValue({
    id: SESSION_ID,
    status: 'open',
    created_at: new Date().toISOString().replace('Z', ''),
    metrics: { typed_chars: DRAFT.length },
  });
  createCompositionSession.mockReset().mockResolvedValue({ id: 'child-session', status: 'open' });
  updateCompositionSession.mockReset().mockResolvedValue({ id: SESSION_ID, status: 'open' });
  listMyCharacterImages.mockReset().mockResolvedValue([IMAGE]);
  useAuthStore.setState({ user: ME });
});

afterEach(() => {
  cleanup();
  useAuthStore.setState({ user: null });
});

// ── Commons defaults ─────────────────────────────────────────────────────────

describe('Commons composer voice', () => {
  it('opens IC for a character-authored post, with OOC selectable', async () => {
    await mountHome();
    expect(voice().value).toBe('ic');
    expect(within(voice()).getByRole('option', { name: 'OOC' })).toBeTruthy();
    fireEvent.change(voice(), { target: { value: 'ooc' } });
    expect(voice().value).toBe('ooc');
  });

  it('keeps an explicit OOC when the posting character changes', async () => {
    await mountHome();
    fireEvent.change(voice(), { target: { value: 'ooc' } });
    const who = await screen.findByDisplayValue('— select character —');
    fireEvent.change(who, { target: { value: String(SHADOW.id) } });
    fireEvent.change(screen.getByDisplayValue('Shadow'), { target: { value: String(PAN.id) } });
    expect(voice().value).toBe('ooc');
  });

  it('returns to IC after an ordinary post, which carried the chosen OOC', async () => {
    await mountHome();
    fireEvent.change(await screen.findByDisplayValue('— select character —'), {
      target: { value: String(PAN.id) },
    });
    fireEvent.change(voice(), { target: { value: 'ooc' } });
    fireEvent.change(composer(), { target: { value: 'Hello all.' } });
    fireEvent.click(postButton());
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    expect(createPost.mock.calls[0][1]).toMatchObject({ content_type: 'ooc', content: 'Hello all.' });
    // An ordinary post has no title field and carries none.
    expect(createPost.mock.calls[0][1]).not.toHaveProperty('title');
    await waitFor(() => expect(voice().value).toBe('ic'));
    expect(screen.queryByTestId('writespace-finalise-banner')).toBeNull();
    expect(screen.queryByRole('button', { name: 'View post' })).toBeNull();
  });
});

// ── WriteSpace → Commons ─────────────────────────────────────────────────────

describe('WriteSpace finalisation in the Commons', () => {
  it('arrives with body, title, character and voice, and adopts the WriteSpace session', async () => {
    seedFinalisation({ contentType: 'ooc' });
    await mountHome();

    expect(screen.getByText('From WriteSpace')).toBeTruthy();
    expect(composer().value).toBe(DRAFT);
    expect((screen.getByLabelText('Post title') as HTMLInputElement).value).toBe('Lanterns');
    expect(voice().value).toBe('ooc');
    expect(await screen.findByDisplayValue('Pan')).toBeTruthy();
    expect(getCompositionSession).toHaveBeenCalledWith(SESSION_ID);
    expect(createCompositionSession).not.toHaveBeenCalled();
    expect(createPost).not.toHaveBeenCalled();
    // Reading does not consume: a reload must find it.
    expect(record()).not.toBeNull();
  });

  it('holds the prefilled text read-only until the session is adopted', async () => {
    seedFinalisation();
    let release!: (v: unknown) => void;
    getCompositionSession.mockImplementation(() => new Promise((r) => { release = r; }));
    await mountHome();
    expect(composer().disabled).toBe(true);
    expect(postButton()).toHaveProperty('disabled', true);
    await act(async () => {
      release({ id: SESSION_ID, status: 'open', metrics: { typed_chars: DRAFT.length } });
    });
    await waitFor(() => expect(composer().disabled).toBe(false));
  });

  it('gives a long WriteSpace piece room to be read', async () => {
    seedFinalisation();
    await mountHome();
    expect(composer().rows).toBe(12);
    expect(composer().className).toContain('min-h-[16rem]');
    expect(composer().className).toContain('max-h-[60vh]');
  });

  it('keeps every post kind available and sends the one chosen', async () => {
    seedFinalisation();
    await mountHome();
    const kind = screen.getByLabelText('Post kind') as HTMLSelectElement;
    expect([...kind.options].map((o) => o.textContent)).toEqual([
      'General',
      'Open Starter',
      'Finished Piece',
    ]);
    fireEvent.change(kind, { target: { value: 'open_starter' } });
    await waitFor(() => expect(composer().disabled).toBe(false));
    fireEvent.click(postButton());
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    expect(createPost.mock.calls[0][1]).toMatchObject({ post_kind: 'open_starter' });
  });

  it('attaches the handed-off character’s image through the existing picker', async () => {
    seedFinalisation();
    await mountHome();
    await screen.findByDisplayValue('Pan');
    fireEvent.click(screen.getByRole('button', { name: /Attach image/ }));
    await waitFor(() =>
      expect(listMyCharacterImages).toHaveBeenCalledWith(expect.objectContaining({ characterId: PAN.id })),
    );
    fireEvent.click(await screen.findByAltText('Pan at dusk'));
    fireEvent.click(screen.getByRole('button', { name: 'Attach selected' }));
    await waitFor(() => expect(composer().disabled).toBe(false));
    fireEvent.click(postButton());
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    expect(createPost.mock.calls[0][1]).toMatchObject({ image_url: IMAGE.url, character_id: PAN.id });
  });

  it('posts once, to the Commons, as the handed-off character with the WriteSpace session', async () => {
    seedFinalisation();
    seedWriteSpaceDraft();
    let release!: (v: unknown) => void;
    createPost.mockImplementation(() => new Promise((r) => { release = r; }));
    await mountHome();
    await screen.findByDisplayValue('Pan');
    await waitFor(() => expect(composer().disabled).toBe(false));

    act(() => {
      postButton().click();
      postButton().click();
    });
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    await act(async () => {
      release({ id: 777, content: DRAFT.trim(), created_at: '2026-09-29T00:00:00Z', mentions: [] });
    });
    expect(createPost).toHaveBeenCalledTimes(1);

    const [realmId, payload] = createPost.mock.calls[0];
    expect(realmId).toBe(COMMONS.id);
    expect(payload).toEqual({
      content: DRAFT.trim(),
      content_type: 'ic',
      post_kind: 'general',
      character_id: PAN.id,
      title: 'Lanterns',
      composition_session_id: SESSION_ID,
    });
  });

  it('succeeds: clears the finalisation and the WriteSpace draft, resets, and links to the post', async () => {
    seedFinalisation();
    seedWriteSpaceDraft();
    await mountHome();
    await screen.findByDisplayValue('Pan');
    await waitFor(() => expect(composer().disabled).toBe(false));
    fireEvent.click(postButton());

    const view = await screen.findByRole('button', { name: 'View post' });
    expect(record()).toBeNull();
    expect(localStorage.getItem(BODY_KEY)).toBeNull();
    expect(localStorage.getItem(TITLE_KEY)).toBeNull();
    expect(localStorage.getItem(SESSION_KEY)).toBeNull();
    expect(composer().value).toBe('');
    expect(voice().value).toBe('ic');
    expect(screen.queryByTestId('writespace-finalise-banner')).toBeNull();
    expect(screen.queryByLabelText('Post title')).toBeNull();

    // The tracker was reset: the next post opens its own session.
    fireEvent.input(composer(), { target: { value: 'Next.' } });
    await waitFor(() => expect(createCompositionSession).toHaveBeenCalledTimes(1));
    expect(createCompositionSession.mock.calls[0][0]).not.toHaveProperty('continues_session_id', SESSION_ID);

    fireEvent.click(view);
    expect(location()).toBe('/posts/777');
  });

  it('fails: keeps the composer, the finalisation and the draft, and retries with the same session', async () => {
    seedFinalisation();
    seedWriteSpaceDraft();
    createPost.mockRejectedValueOnce(new Error('You can only post as your own character.'));
    await mountHome();
    await screen.findByDisplayValue('Pan');
    await waitFor(() => expect(composer().disabled).toBe(false));
    fireEvent.click(postButton());

    expect(await screen.findByText('You can only post as your own character.')).toBeTruthy();
    expect(composer().value).toBe(DRAFT);
    expect(record()).not.toBeNull();
    expect(localStorage.getItem(BODY_KEY)).toBe(DRAFT);
    expect(localStorage.getItem(SESSION_KEY)).toBe(SESSION_ID);

    fireEvent.click(postButton());
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(2));
    expect(createPost.mock.calls[1][1].composition_session_id).toBe(SESSION_ID);
  });

  it('a reload restores the finalisation', async () => {
    seedFinalisation();
    await mountHome();
    cleanup();
    await mountHome();
    expect(composer().value).toBe(DRAFT);
    expect(screen.getByText('From WriteSpace')).toBeTruthy();
  });

  it('Back to WriteSpace returns there with the draft and its session untouched', async () => {
    seedFinalisation();
    seedWriteSpaceDraft();
    await mountHome();
    await waitFor(() => expect(composer().disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: 'Back to WriteSpace' }));
    expect(location()).toBe('/workspace');
    expect(localStorage.getItem(BODY_KEY)).toBe(DRAFT);
    expect(localStorage.getItem(SESSION_KEY)).toBe(SESSION_ID);
    expect(createPost).not.toHaveBeenCalled();
  });

  it('Discard drops only the prepared post; the WriteSpace draft survives', async () => {
    seedFinalisation();
    seedWriteSpaceDraft();
    await mountHome();
    await waitFor(() => expect(composer().disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }));

    expect(record()).toBeNull();
    expect(composer().value).toBe('');
    expect(screen.queryByTestId('writespace-finalise-banner')).toBeNull();
    expect(screen.queryByLabelText('Post title')).toBeNull();
    expect(localStorage.getItem(BODY_KEY)).toBe(DRAFT);
    expect(localStorage.getItem(SESSION_KEY)).toBe(SESSION_ID);

    // Whatever is written next does not ride on the WriteSpace session.
    fireEvent.input(composer(), { target: { value: 'Something else.' } });
    await waitFor(() => expect(createCompositionSession).toHaveBeenCalledTimes(1));
  });

  it('ignores a finalisation addressed to a realm', async () => {
    seedFinalisation({ realmId: HARBOUR.id });
    await mountHome();
    expect(composer().value).toBe('');
    expect(screen.queryByText('From WriteSpace')).toBeNull();
    expect(getCompositionSession).not.toHaveBeenCalled();
    expect(record()).not.toBeNull();
  });

  it('falls back to the usual choice when the handed-off character is no longer yours', async () => {
    seedFinalisation({ characterId: 999 });
    await mountHome();
    expect(await screen.findByDisplayValue('— select character —')).toBeTruthy();
    expect(composer().value).toBe(DRAFT);
  });

  it('does not touch the copy-for-posting handoff', async () => {
    seedFinalisation();
    sessionStorage.setItem(COPY_HANDOFF_KEY, 'left-by-copy');
    await mountHome();
    await waitFor(() => expect(composer().disabled).toBe(false));
    expect(sessionStorage.getItem(COPY_HANDOFF_KEY)).toBe('left-by-copy');
  });
});

// ── what reaches the server ─────────────────────────────────────────────────

describe('evidence handed to the server', () => {
  async function postFinalised() {
    await mountHome();
    await screen.findByDisplayValue('Pan');
    await waitFor(() => expect(composer().disabled).toBe(false));
    fireEvent.click(postButton());
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    return createPost.mock.calls[0][1];
  }

  it('typed WriteSpace text keeps the counters the server observed', async () => {
    seedFinalisation();
    const payload = await postFinalised();
    expect(payload.composition_session_id).toBe(SESSION_ID);
    expect(lastPatch()).toMatchObject({
      typed_chars: DRAFT.length,
      inserted_chars: 0,
      internal_insert_chars: 0,
    });
  });

  it('mostly pasted WriteSpace text stays pasted — the prefill is not counted as typing', async () => {
    seedFinalisation();
    getCompositionSession.mockResolvedValue({
      id: SESSION_ID,
      status: 'open',
      metrics: { typed_chars: 4, inserted_chars: DRAFT.length - 4, insertion_count: 1 },
    });
    await postFinalised();
    expect(lastPatch()).toMatchObject({
      typed_chars: 4,
      inserted_chars: DRAFT.length - 4,
      internal_insert_chars: 0,
    });
  });

  it('an unknown or foreign session is only a bounded claim on a child session', async () => {
    seedFinalisation({ sessionId: 'invented-by-hand' });
    getCompositionSession.mockRejectedValue(new Error('Not found'));
    const payload = await postFinalised();
    expect(createCompositionSession).toHaveBeenCalledWith(
      expect.objectContaining({ surface: 'commons_composer', continues_session_id: 'invented-by-hand' }),
    );
    expect(payload.composition_session_id).toBe('child-session');
    // Claimed as internal, typed nothing: the server credits it only up to what
    // a parent it owns was seen to type — for an unknown id, nothing.
    expect(lastPatch()).toMatchObject({
      typed_chars: 0,
      inserted_chars: DRAFT.length,
      internal_insert_chars: DRAFT.length,
    });
  });

  it('a WriteSpace session too old to be claimed is continued, not adopted', async () => {
    seedFinalisation();
    getCompositionSession.mockResolvedValue({
      id: SESSION_ID,
      status: 'open',
      created_at: new Date(Date.now() - 30 * 3600_000).toISOString().replace('Z', ''),
      metrics: { typed_chars: DRAFT.length },
    });
    const payload = await postFinalised();
    expect(createCompositionSession).toHaveBeenCalledWith(
      expect.objectContaining({ continues_session_id: SESSION_ID }),
    );
    expect(payload.composition_session_id).toBe('child-session');
    expect(lastPatch()).toMatchObject({ typed_chars: 0, internal_insert_chars: DRAFT.length });
  });

  it('a record with no session posts with no borrowed evidence', async () => {
    seedFinalisation({ sessionId: null });
    await mountHome();
    await screen.findByDisplayValue('Pan');
    expect(composer().disabled).toBe(false);
    fireEvent.click(postButton());
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    expect(getCompositionSession).not.toHaveBeenCalled();
    expect(createCompositionSession.mock.calls.every(([p]) => !p.continues_session_id)).toBe(true);
  });
});

// ── WriteSpace → Realm ───────────────────────────────────────────────────────

describe('WriteSpace finalisation in a Realm', () => {
  it('the targeted realm opens its New Post form prefilled and adopts the session', async () => {
    seedFinalisation({ realmId: HARBOUR.id, contentType: 'ooc' });
    seedWriteSpaceDraft();
    renderAt(`/realms/${HARBOUR.id}`);

    expect(await screen.findByText('From WriteSpace')).toBeTruthy();
    expect(realmContent().value).toBe(DRAFT);
    expect(screen.getByDisplayValue('Lanterns')).toBeTruthy();
    expect(screen.getByDisplayValue('Out-of-Character (OOC)')).toBeTruthy();
    expect(await screen.findByDisplayValue('Pan')).toBeTruthy();
    expect(getCompositionSession).toHaveBeenCalledWith(SESSION_ID);
    // The realm's own controls are all there.
    expect(screen.getByDisplayValue('General')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Attach image/ })).toHaveProperty('disabled', false);

    await waitFor(() => expect(realmContent().disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: 'Post' }));
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    const [realmId, payload] = createPost.mock.calls[0];
    expect(realmId).toBe(HARBOUR.id);
    expect(payload).toMatchObject({
      title: 'Lanterns',
      content: DRAFT,
      content_type: 'ooc',
      post_kind: 'general',
      character_id: PAN.id,
      composition_session_id: SESSION_ID,
    });
    await waitFor(() => expect(record()).toBeNull());
    expect(localStorage.getItem(BODY_KEY)).toBeNull();
    expect(localStorage.getItem(SESSION_KEY)).toBeNull();
  });

  it('a failed realm post keeps the form, the finalisation and the draft', async () => {
    seedFinalisation({ realmId: HARBOUR.id });
    seedWriteSpaceDraft();
    createPost.mockRejectedValueOnce(new Error('You must be a member of this realm to post'));
    renderAt(`/realms/${HARBOUR.id}`);
    await screen.findByDisplayValue('Pan');
    await waitFor(() => expect(realmContent().disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: 'Post' }));
    expect(await screen.findByText(/Failed to create post/)).toBeTruthy();
    expect(realmContent().value).toBe(DRAFT);
    expect(record()).not.toBeNull();
    expect(localStorage.getItem(SESSION_KEY)).toBe(SESSION_ID);
  });

  it('another realm does not consume it', async () => {
    seedFinalisation({ realmId: HARBOUR.id });
    renderAt('/realms/10');
    expect(await screen.findByRole('button', { name: '+ New Post' })).toBeTruthy();
    expect(screen.queryByText('From WriteSpace')).toBeNull();
    expect(getCompositionSession).not.toHaveBeenCalled();
    expect(record()).not.toBeNull();
  });

  it('a Commons finalisation is never consumed by a realm page, the Commons realm included', async () => {
    seedFinalisation({ realmId: null });
    renderAt(`/realms/${COMMONS.id}`);
    expect(await screen.findByRole('button', { name: '+ New Post' })).toBeTruthy();
    expect(screen.queryByText('From WriteSpace')).toBeNull();
    expect(record()).not.toBeNull();
  });

  it('Discard empties the form and keeps the WriteSpace draft', async () => {
    seedFinalisation({ realmId: HARBOUR.id });
    seedWriteSpaceDraft();
    renderAt(`/realms/${HARBOUR.id}`);
    await screen.findByText('From WriteSpace');
    await waitFor(() => expect(realmContent().disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
    expect(record()).toBeNull();
    expect(realmContent().value).toBe('');
    expect(localStorage.getItem(BODY_KEY)).toBe(DRAFT);
  });
});

describe('ordinary realm posting', () => {
  it('opens IC — the Commons realm included — and posts as before', async () => {
    for (const realm of [HARBOUR, COMMONS]) {
      renderAt(`/realms/${realm.id}`);
      fireEvent.click(await screen.findByRole('button', { name: '+ New Post' }));
      expect(screen.getByDisplayValue('In-Character (IC)')).toBeTruthy();
      expect(screen.queryByText('From WriteSpace')).toBeNull();
      cleanup();
    }

    renderAt(`/realms/${HARBOUR.id}`);
    fireEvent.click(await screen.findByRole('button', { name: '+ New Post' }));
    fireEvent.change(await screen.findByDisplayValue('— select character —'), {
      target: { value: String(SHADOW.id) },
    });
    fireEvent.change(screen.getByDisplayValue('In-Character (IC)'), { target: { value: 'ooc' } });
    fireEvent.change(realmContent(), { target: { value: 'A realm post.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Post' }));
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    expect(createPost.mock.calls[0][0]).toBe(HARBOUR.id);
    expect(createPost.mock.calls[0][1]).toMatchObject({
      content: 'A realm post.',
      content_type: 'ooc',
      post_kind: 'general',
      character_id: SHADOW.id,
    });
    expect(getCompositionSession).not.toHaveBeenCalled();
  });
});

// ── Character gallery composer ───────────────────────────────────────────────

describe('Character gallery PostComposer', () => {
  const selected = (label: string) =>
    screen.getByRole('button', { name: label }).className.includes('bg-gem text-gem-ink');

  it('opens IC, allows OOC, and reopens IC', async () => {
    const view = (open: boolean) => (
      <MemoryRouter>
        <PostComposer open={open} onClose={() => {}} characterId={PAN.id} characterName="Pan" />
      </MemoryRouter>
    );
    const { rerender } = render(view(true));
    expect(selected('IC')).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'OOC' }));
    expect(selected('OOC')).toBe(true);
    rerender(view(false));
    rerender(view(true));
    expect(selected('IC')).toBe(true);
  });
});
