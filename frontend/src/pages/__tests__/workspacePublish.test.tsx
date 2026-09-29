// @vitest-environment jsdom
/**
 * WriteSpace hands a finished draft to the composer that publishes it.
 *
 * "Continue to publish" creates no post. It flushes the draft's composition
 * counters (without claiming the session), writes the finalisation record and
 * navigates to the Commons or the chosen Realm, whose composer prepares and
 * creates the post. The control is reachable in every mode, disabled for
 * "Yourself (OOC)", and makes one handoff however often it is clicked.
 *
 * The real CompositionTracker runs throughout. The draft and its session id are
 * seeded under the keys WriteSpace autosaves to, and the session is adopted
 * through the tracker's own resume path, so every mode is exercised with the
 * same evidence a returning writer would carry.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
const FINALISE_KEY = 'ficshon.writespace.finalise';
const COPY_HANDOFF_KEY = 'ficshon.composition.handoff';
const finaliseRecord = () => JSON.parse(sessionStorage.getItem(FINALISE_KEY) ?? 'null');
const location = () => screen.getByTestId('location').textContent;

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

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('Continue to publish is reachable in every mode', () => {
  it.each(['write', 'preview', 'review'])('is present and enabled in %s mode', async (mode) => {
    seedDraft({ mode });
    await mount();
    expect(headerPublish()).toHaveProperty('disabled', false);
    expect(headerPublish().textContent).toBe('Continue to publish');
  });

  it('hands off from Review mode, where the sidebar carries no control', async () => {
    seedDraft({ mode: 'review' });
    await mount();
    fireEvent.click(headerPublish());
    await waitFor(() => expect(location()).toBe('/'));
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
    await waitFor(() => expect(location()).toBe('/'));
  });

  it('every entry point says what it does — none claims to publish', async () => {
    seedDraft();
    await mount();
    const entryPoints = screen.getAllByRole('button', { name: 'Continue to publish' });
    // Header, sidebar, mobile bar.
    expect(entryPoints.length).toBe(3);
    expect(screen.queryByRole('button', { name: /^Publish/ })).toBeNull();
  });

  it('no longer offers the legacy copy-and-paste route', async () => {
    seedDraft();
    await mount();
    expect(screen.queryByRole('button', { name: 'Copy for posting' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Go to Home/ })).toBeNull();
    expect(screen.queryByText(/paste/i)).toBeNull();
    // What stays.
    expect(screen.getByRole('button', { name: 'Download text' })).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Clear draft' }).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Open StoryLab' })).toBeTruthy();
  });
});

describe('destination wording', () => {
  it('labels the Commons destination "Commons", not as an action', async () => {
    seedDraft();
    await mount();
    expect(screen.queryByRole('option', { name: 'Publish to Commons' })).toBeNull();
    expect(screen.getAllByRole('option', { name: 'Commons' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('option', { name: 'Harbour' }).length).toBeGreaterThan(0);
  });
});

describe('the handoff', () => {
  it('creates no post, flushes the session, writes the record and opens the Commons', async () => {
    seedDraft();
    await mount();
    fireEvent.click(headerPublish());
    await waitFor(() => expect(location()).toBe('/'));

    expect(createPost).not.toHaveBeenCalled();
    expect(finaliseRecord()).toMatchObject({
      v: 1,
      sessionId: SESSION_ID,
      characterId: PAN.id,
      contentType: 'ic',
      title: 'Lanterns',
      body: DRAFT,
      realmId: null,
    });
    expect(typeof finaliseRecord().createdAt).toBe('number');
    // Counters reach the server before the destination reads them — a flush,
    // not a claim: nothing about the session is spent here.
    expect(updateCompositionSession).toHaveBeenCalledWith(SESSION_ID, expect.any(Object));
  });

  it('flushes the counters before navigating', async () => {
    seedDraft();
    let release!: (v: unknown) => void;
    updateCompositionSession.mockImplementation(() => new Promise((r) => { release = r; }));
    await mount();
    fireEvent.click(headerPublish());
    await waitFor(() => expect(updateCompositionSession).toHaveBeenCalledTimes(1));
    // Still waiting on the flush: no record, no navigation, and it says so.
    expect(finaliseRecord()).toBeNull();
    expect(location()).toBe('/workspace');
    expect(headerPublish().textContent).toBe('Preparing…');
    await act(async () => { release({ id: SESSION_ID, status: 'open' }); });
    await waitFor(() => expect(location()).toBe('/'));
  });

  it('opens the chosen realm when a realm is the destination', async () => {
    seedDraft({ realm: String(HARBOUR.id) });
    await mount();
    await screen.findAllByRole('option', { name: 'Harbour' });
    fireEvent.click(headerPublish());
    await waitFor(() => expect(location()).toBe(`/realms/${HARBOUR.id}`));
    expect(finaliseRecord()).toMatchObject({ realmId: HARBOUR.id, sessionId: SESSION_ID });
    expect(createPost).not.toHaveBeenCalled();
  });

  it('keeps the WriteSpace draft and its session for Back to WriteSpace', async () => {
    seedDraft();
    await mount();
    fireEvent.click(headerPublish());
    await waitFor(() => expect(location()).toBe('/'));
    expect(localStorage.getItem(BODY_KEY)).toBe(DRAFT);
    expect(localStorage.getItem(TITLE_KEY)).toBe('Lanterns');
    expect(localStorage.getItem(SESSION_KEY)).toBe(SESSION_ID);
  });

  it('carries a session opened by typing in the editor', async () => {
    await mount0();
    const editor = screen.getByLabelText('WriteSpace editor') as HTMLTextAreaElement;
    fireEvent.input(editor, { target: { value: 'Typed here.' } });
    await waitFor(() => expect(createCompositionSession).toHaveBeenCalled());
    expect(createCompositionSession.mock.calls[0][0]).toMatchObject({ surface: 'workspace' });
    fireEvent.click(headerPublish());
    await waitFor(() => expect(location()).toBe('/'));
    expect(finaliseRecord()).toMatchObject({ body: 'Typed here.', sessionId: 'fresh-session' });
    expect(updateCompositionSession).toHaveBeenCalledWith('fresh-session', expect.any(Object));
  });

  it('never writes or takes the copy-for-posting handoff', async () => {
    seedDraft();
    sessionStorage.setItem(COPY_HANDOFF_KEY, 'left-by-copy');
    await mount();
    fireEvent.click(headerPublish());
    await waitFor(() => expect(location()).toBe('/'));
    expect(sessionStorage.getItem(COPY_HANDOFF_KEY)).toBe('left-by-copy');
    expect(createCompositionSession).not.toHaveBeenCalled();
  });

  it('does not hand off when the counters cannot be reported', async () => {
    seedDraft({ mode: 'review' });
    updateCompositionSession.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await mount();
    fireEvent.click(headerPublish());
    expect(
      await screen.findByText('Couldn\u2019t prepare the post. Check your connection and try again.'),
    ).toBeTruthy();
    expect(finaliseRecord()).toBeNull();
    expect(location()).toBe('/workspace');
    expect(localStorage.getItem(SESSION_KEY)).toBe(SESSION_ID);

    // Retry goes through.
    fireEvent.click(headerPublish());
    await waitFor(() => expect(location()).toBe('/'));
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
  it('disables every Continue to publish control and says why', async () => {
    seedDraft({ character: '0' });
    await mount();
    const entryPoints = screen.getAllByRole('button', { name: 'Continue to publish' });
    expect(entryPoints.length).toBe(3);
    entryPoints.forEach((b) => expect(b).toHaveProperty('disabled', true));
    expect(screen.getAllByText(OOC_HINT).length).toBeGreaterThan(0);
    fireEvent.click(headerPublish());
    expect(finaliseRecord()).toBeNull();
    expect(location()).toBe('/workspace');
  });
});

describe('duplicate activation', () => {
  it('a rapid double click across entry points makes one handoff and one navigation', async () => {
    seedDraft();
    let release!: (v: unknown) => void;
    updateCompositionSession.mockImplementation(() => new Promise((r) => { release = r; }));
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    await mount();

    // Every click lands in one act(), before React can re-render any button as
    // disabled: a double click on the header, then the sidebar and mobile-bar
    // controls, which share the same guard.
    const entryPoints = screen.getAllByRole('button', { name: 'Continue to publish' }) as HTMLButtonElement[];
    act(() => {
      headerPublish().click();
      headerPublish().click();
      entryPoints.forEach((b) => b.click());
    });
    await waitFor(() => expect(updateCompositionSession).toHaveBeenCalledTimes(1));
    await act(async () => { release({ id: SESSION_ID, status: 'open' }); });
    await waitFor(() => expect(location()).toBe('/'));

    expect(updateCompositionSession).toHaveBeenCalledTimes(1);
    expect(setItem.mock.calls.filter(([k]) => k === FINALISE_KEY)).toHaveLength(1);
    expect(createPost).not.toHaveBeenCalled();
  });
});

describe('stale finalisation', () => {
  it('reopening WriteSpace clears a finalisation left behind', async () => {
    sessionStorage.setItem(FINALISE_KEY, JSON.stringify({ v: 1, body: 'older version' }));
    seedDraft();
    await mount();
    expect(sessionStorage.getItem(FINALISE_KEY)).toBeNull();
    // The draft itself is untouched.
    expect(localStorage.getItem(BODY_KEY)).toBe(DRAFT);
  });
});
