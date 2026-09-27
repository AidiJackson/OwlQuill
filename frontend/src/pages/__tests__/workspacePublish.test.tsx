// @vitest-environment jsdom
/**
 * WriteSpace publishing is reachable, honest about who it posts as, and posts
 * exactly once through the canonical endpoint.
 *
 * WriteSpace already had the right publish path — `createPost` with its own
 * `workspace` composition session, so provenance is decided server-side from
 * what was typed here. What was broken was reaching it: on desktop the only
 * Publish button lived in the sidebar, which Review replaces and Focus hides,
 * while the header offered a destination option labelled "Publish to Commons"
 * that did nothing when chosen.
 *
 * The real CompositionTracker runs throughout. The draft and its session id are
 * seeded under the keys WriteSpace autosaves to, and the session is adopted
 * through the tracker's own resume path, so every mode is exercised with the
 * same evidence a returning writer would carry.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const createPost = vi.fn();
const getRealms = vi.fn();
const getCharacters = vi.fn();
const createCompositionSession = vi.fn();
const getCompositionSession = vi.fn();
const updateCompositionSession = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: new Proxy(
    {},
    {
      get: (_t, key: string) => {
        const named: Record<string, unknown> = {
          createPost,
          getRealms,
          getCharacters,
          createCompositionSession,
          getCompositionSession,
          updateCompositionSession,
        };
        if (key in named) return named[key];
        if (key === 'then') return undefined;
        return () => Promise.resolve([]);
      },
    },
  ),
}));

import Workspace from '@/pages/Workspace';

const BODY_KEY = 'ficshon.workspace.body';
const TITLE_KEY = 'ficshon.workspace.title';
const MODE_KEY = 'ficshon.writespace.mode';
const REALM_KEY = 'ficshon.writespace.selected_realm_id';
const CHARACTER_KEY = 'ficshon.writespace.selected_character_id';
const SESSION_KEY = 'ficshon.writespace.composition_session_id';

const SESSION_ID = '11111111-2222-4333-8444-555555555555';
const DRAFT = 'Pan crossed the harbour at dusk, counting lanterns.';
const OOC_HINT = 'Posts are authored by characters — choose a character to publish.';

const COMMONS = { id: 1, name: 'Commons', is_commons: true };
const HARBOUR = { id: 9, name: 'Harbour', is_commons: false };
const PAN = { id: 42, name: 'Pan' };

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location">{loc.pathname}</div>;
}

function seedDraft(over: { mode?: string; realm?: string; character?: string } = {}) {
  localStorage.setItem(BODY_KEY, DRAFT);
  localStorage.setItem(TITLE_KEY, 'Lanterns');
  localStorage.setItem(SESSION_KEY, SESSION_ID);
  localStorage.setItem(MODE_KEY, over.mode ?? 'write');
  localStorage.setItem(REALM_KEY, over.realm ?? '');
  localStorage.setItem(CHARACTER_KEY, over.character ?? String(PAN.id));
}

async function mount() {
  render(
    <MemoryRouter initialEntries={['/workspace']}>
      <Routes>
        <Route path="*" element={<><Workspace /><LocationProbe /></>} />
      </Routes>
    </MemoryRouter>,
  );
  // Characters loaded (the selector offers Pan) and the draft's session adopted.
  await screen.findAllByRole('option', { name: 'Pan' });
  await waitFor(() => expect(getCompositionSession).toHaveBeenCalledWith(SESSION_ID));
}

const headerPublish = () => screen.getByTestId('ws-header-publish');

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  createPost.mockReset().mockResolvedValue({ id: 777 });
  getRealms.mockReset().mockResolvedValue([COMMONS, HARBOUR]);
  getCharacters.mockReset().mockResolvedValue([PAN]);
  createCompositionSession.mockReset().mockResolvedValue({ id: 'fresh-session', status: 'open' });
  getCompositionSession
    .mockReset()
    .mockResolvedValue({ id: SESSION_ID, status: 'open', metrics: { typed_chars: DRAFT.length } });
  updateCompositionSession.mockReset().mockResolvedValue({ id: SESSION_ID, status: 'open' });
});

afterEach(() => cleanup());

describe('desktop header Publish is reachable in every mode', () => {
  it.each(['write', 'preview', 'review'])('is present and enabled in %s mode', async (mode) => {
    seedDraft({ mode });
    await mount();
    expect(headerPublish()).toHaveProperty('disabled', false);
    expect(headerPublish().textContent).toBe('Publish');
  });

  it('publishes from Review mode, where the sidebar carries no publish control', async () => {
    seedDraft({ mode: 'review' });
    await mount();
    fireEvent.click(headerPublish());
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
  });

  it('stays reachable in Focus mode, outside the hidden sidebar', async () => {
    seedDraft();
    await mount();
    fireEvent.click(screen.getByRole('button', { name: 'Focus' }));
    expect(screen.getByRole('button', { name: 'Exit focus' })).toBeTruthy();
    // Focus fades the sidebar <aside> to opacity-0 / pointer-events-none; the
    // header control must not live inside it.
    expect(headerPublish().closest('aside')).toBeNull();
    fireEvent.click(headerPublish());
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
  });
});

describe('destination wording', () => {
  it('labels the Commons destination "Commons", not as an action', async () => {
    seedDraft();
    await mount();
    expect(screen.queryByRole('option', { name: 'Publish to Commons' })).toBeNull();
    expect(screen.getAllByRole('option', { name: 'Commons' }).length).toBeGreaterThan(0);
    // Realm destinations are unchanged.
    expect(screen.getAllByRole('option', { name: 'Harbour' }).length).toBeGreaterThan(0);
  });
});

describe('the canonical create payload', () => {
  it('posts to Commons as the selected character, IC, with the workspace session', async () => {
    seedDraft();
    await mount();
    fireEvent.click(headerPublish());
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));

    const [realmId, payload] = createPost.mock.calls[0];
    expect(realmId).toBe(COMMONS.id);
    expect(payload).toEqual({
      content: DRAFT,
      content_type: 'ic',
      character_id: PAN.id,
      title: 'Lanterns',
      composition_session_id: SESSION_ID,
    });
    // Counters are flushed to that same session before the post is created.
    expect(updateCompositionSession).toHaveBeenCalledWith(SESSION_ID, expect.any(Object));
    expect(updateCompositionSession.mock.invocationCallOrder[0]).toBeLessThan(
      createPost.mock.invocationCallOrder[0],
    );
  });

  it('posts to the selected realm id when a realm is the destination', async () => {
    seedDraft({ realm: String(HARBOUR.id) });
    await mount();
    await screen.findAllByRole('option', { name: 'Harbour' });
    fireEvent.click(headerPublish());
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    expect(createPost.mock.calls[0][0]).toBe(HARBOUR.id);
  });

  it('carries a session opened by typing in the editor', async () => {
    await mount0();
    const editor = screen.getByLabelText('WriteSpace editor') as HTMLTextAreaElement;
    fireEvent.input(editor, { target: { value: 'Typed here.' } });
    await waitFor(() => expect(createCompositionSession).toHaveBeenCalled());
    expect(createCompositionSession.mock.calls[0][0]).toMatchObject({ surface: 'workspace' });
    fireEvent.click(headerPublish());
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    expect(createPost.mock.calls[0][1]).toMatchObject({
      content: 'Typed here.',
      composition_session_id: 'fresh-session',
    });
  });
});

/** Mount with no restored draft — a writer starting fresh as Pan. */
async function mount0() {
  localStorage.setItem(CHARACTER_KEY, String(PAN.id));
  render(
    <MemoryRouter initialEntries={['/workspace']}>
      <Routes>
        <Route path="*" element={<><Workspace /><LocationProbe /></>} />
      </Routes>
    </MemoryRouter>,
  );
  await screen.findAllByRole('option', { name: 'Pan' });
}

describe('Yourself (OOC)', () => {
  it('disables every Publish control and says why', async () => {
    seedDraft({ character: '0' });
    await mount();
    expect(headerPublish()).toHaveProperty('disabled', true);
    expect(screen.getByRole('button', { name: 'Publish to Commons' })).toHaveProperty('disabled', true);
    expect(screen.getAllByText(OOC_HINT).length).toBeGreaterThan(0);
    fireEvent.click(headerPublish());
    expect(createPost).not.toHaveBeenCalled();
  });
});

describe('duplicate submission', () => {
  it('a rapid double click produces exactly one createPost', async () => {
    seedDraft();
    let release!: (v: unknown) => void;
    createPost.mockImplementation(() => new Promise((r) => { release = r; }));
    await mount();

    // Every click lands in one act(), before React can re-render any button as
    // disabled: a double click on the header, then the sidebar and mobile-bar
    // controls, which share the same guard.
    const entryPoints = screen.getAllByRole('button', { name: /^Publish/ }) as HTMLButtonElement[];
    expect(entryPoints.length).toBe(3);
    act(() => {
      headerPublish().click();
      headerPublish().click();
      entryPoints.forEach((b) => b.click());
    });
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(1));
    await act(async () => { release({ id: 777 }); });
    expect(createPost).toHaveBeenCalledTimes(1);
  });
});

describe('failure', () => {
  it('keeps the draft and its session, shows the server message, and retries with the same session', async () => {
    seedDraft({ mode: 'review' });
    createPost.mockRejectedValueOnce(new Error('You must be a member of this realm to post'));
    await mount();
    fireEvent.click(headerPublish());

    expect(await screen.findByText('You must be a member of this realm to post')).toBeTruthy();
    expect(localStorage.getItem(BODY_KEY)).toBe(DRAFT);
    expect(localStorage.getItem(SESSION_KEY)).toBe(SESSION_ID);

    fireEvent.click(headerPublish());
    await waitFor(() => expect(createPost).toHaveBeenCalledTimes(2));
    expect(createPost.mock.calls[1][1].composition_session_id).toBe(SESSION_ID);
  });

  it('falls back to a generic message for errors that are not user-facing', async () => {
    seedDraft({ mode: 'review' });
    createPost.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await mount();
    fireEvent.click(headerPublish());
    expect(await screen.findByText('Post failed. Try again.')).toBeTruthy();
    expect(screen.queryByText(/Failed to fetch/)).toBeNull();
  });
});

describe('success', () => {
  it('clears the draft, spends the session, resets the tracker and links to the new post', async () => {
    seedDraft({ mode: 'review' });
    await mount();
    fireEvent.click(headerPublish());

    expect(await screen.findByText('Published to Commons.')).toBeTruthy();
    expect(localStorage.getItem(BODY_KEY)).toBeNull();
    expect(localStorage.getItem(TITLE_KEY)).toBeNull();
    expect(localStorage.getItem(SESSION_KEY)).toBeNull();
    // The success state is shown in place — no automatic redirect.
    expect(screen.getByTestId('location').textContent).toBe('/workspace');

    // Tracker reset: the next piece opens a fresh session rather than reusing
    // the one the server has already spent.
    fireEvent.click(screen.getByRole('button', { name: 'Write' }));
    const editor = screen.getByLabelText('WriteSpace editor');
    fireEvent.input(editor, { target: { value: 'Next.' } });
    await waitFor(() => expect(createCompositionSession).toHaveBeenCalledTimes(1));

    fireEvent.click(within(screen.getByTestId('ws-publish-status')).getByRole('button', { name: 'View post' }));
    expect(screen.getByTestId('location').textContent).toBe('/posts/777');
  });

  it('the sidebar View post also targets the created post', async () => {
    seedDraft();
    await mount();
    fireEvent.click(headerPublish());
    await screen.findByText('Published');
    const buttons = screen.getAllByRole('button', { name: 'View post' });
    fireEvent.click(buttons[buttons.length - 1]);
    expect(screen.getByTestId('location').textContent).toBe('/posts/777');
  });
});
