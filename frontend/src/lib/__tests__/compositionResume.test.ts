import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * Resuming a restored draft's session.
 *
 * A composition session lives as long as the component that opened it; an
 * autosaved draft outlives it. Before this, reopening WriteSpace meant the
 * restored text had been typed into a session nobody was holding any more, the
 * new session reported almost nothing, and the finished piece posted as
 * "Created elsewhere". These tests pin the two ways back — and, just as
 * importantly, pin that neither of them invents evidence.
 */

const getCompositionSession = vi.fn();
const createCompositionSession = vi.fn();
const updateCompositionSession = vi.fn();

vi.mock('../apiClient', () => ({
  apiClient: {
    getCompositionSession: (...args: unknown[]) => getCompositionSession(...args),
    createCompositionSession: (...args: unknown[]) => createCompositionSession(...args),
    updateCompositionSession: (...args: unknown[]) => updateCompositionSession(...args),
  },
}));

const { CompositionTracker } = await import('../composition');

/** The counters handed to the server by the most recent commit. */
async function committedMetrics(tracker: InstanceType<typeof CompositionTracker>) {
  await tracker.commit();
  const calls = updateCompositionSession.mock.calls;
  return calls[calls.length - 1]?.[1];
}

beforeEach(() => {
  getCompositionSession.mockReset();
  createCompositionSession.mockReset();
  updateCompositionSession.mockReset();
  updateCompositionSession.mockResolvedValue({ id: 'x', status: 'open' });
});

describe('CompositionTracker.resume', () => {
  it('adopts the still-open session and the counters the SERVER holds', async () => {
    // The 4,000 characters were typed here yesterday. The browser forgot; the
    // server did not, and the server's record is the one that counts.
    getCompositionSession.mockResolvedValue({
      id: 'sess-1',
      status: 'open',
      metrics: { typed_chars: 4000, inserted_chars: 0 },
    });

    const tracker = new CompositionTracker('workspace');
    const id = await tracker.resume('sess-1', 4000);

    expect(id).toBe('sess-1');
    expect(createCompositionSession).not.toHaveBeenCalled();
    expect(await committedMetrics(tracker)).toMatchObject({
      typed_chars: 4000,
      inserted_chars: 0,
      internal_insert_chars: 0,
    });
  });

  it('ignores unknown keys in the stored session state', async () => {
    // metrics_json is an open slot shared with autosave and analytics. Only
    // the counters this module defines may become metrics.
    getCompositionSession.mockResolvedValue({
      id: 'sess-1',
      status: 'open',
      metrics: { typed_chars: 120, draft_body: 'not a counter', typed_words: 90 },
    });

    const tracker = new CompositionTracker('workspace');
    await tracker.resume('sess-1', 120);

    const metrics = await committedMetrics(tracker);
    expect(metrics).toMatchObject({ typed_chars: 120 });
    expect(metrics).not.toHaveProperty('draft_body');
    expect(metrics).not.toHaveProperty('typed_words');
  });

  it('continues a spent session as an internal transfer, which the server bounds', async () => {
    // Expired or already committed. The restored text is declared an internal
    // transfer from the parent — a claim, not a grant: the server credits it
    // only as far as the parent was observed to type.
    getCompositionSession.mockResolvedValue({ id: 'sess-1', status: 'committed' });
    createCompositionSession.mockResolvedValue({ id: 'sess-2', status: 'open' });

    const tracker = new CompositionTracker('workspace');
    const id = await tracker.resume('sess-1', 3200);

    expect(id).toBe('sess-2');
    expect(createCompositionSession).toHaveBeenCalledWith(
      expect.objectContaining({ continues_session_id: 'sess-1' }),
    );
    expect(await committedMetrics(tracker)).toMatchObject({
      typed_chars: 0,
      inserted_chars: 3200,
      internal_insert_chars: 3200,
    });
  });

  it('never claims typing it did not observe', async () => {
    // The continuation path must not put the restored draft in `typed_chars`.
    // That field is the one thing that earns "Written in Ficshon", and nothing
    // here watched those characters being typed.
    getCompositionSession.mockRejectedValue(new Error('404'));
    createCompositionSession.mockResolvedValue({ id: 'sess-2', status: 'open' });

    const tracker = new CompositionTracker('workspace');
    await tracker.resume('missing', 5000);

    expect((await committedMetrics(tracker)).typed_chars).toBe(0);
  });

  it('keeps what was typed while the lookup was still in flight', async () => {
    // A fast writer types into the restored draft before the round-trip
    // returns. Those characters must land on top of the server's totals, not
    // be wiped by them — and must not open a second, competing session.
    let release: (v: unknown) => void = () => {};
    getCompositionSession.mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );

    const tracker = new CompositionTracker('workspace');
    const resuming = tracker.resume('sess-1', 4000);
    tracker.noteEditorEdit(50);

    release({ id: 'sess-1', status: 'open', metrics: { typed_chars: 4000 } });
    await resuming;

    expect(createCompositionSession).not.toHaveBeenCalled();
    expect((await committedMetrics(tracker)).typed_chars).toBe(4050);
  });

  it('does nothing without a stored session id', async () => {
    const tracker = new CompositionTracker('workspace');
    expect(await tracker.resume(null, 900)).toBeNull();
    expect(getCompositionSession).not.toHaveBeenCalled();
    expect(createCompositionSession).not.toHaveBeenCalled();
  });

  it('does nothing when there is no restored draft to account for', async () => {
    const tracker = new CompositionTracker('workspace');
    expect(await tracker.resume('sess-1', 0)).toBeNull();
    expect(getCompositionSession).not.toHaveBeenCalled();
  });
});

describe('CompositionTracker.noteEditorEdit', () => {
  it('counts what the editor’s own tools add to the draft', async () => {
    // Scene breaks, headings and grammar fixes rewrite the textarea through
    // React state and fire no input event. Uncounted, they make the session
    // under-report and the post reads as created elsewhere.
    createCompositionSession.mockResolvedValue({ id: 'sess-3', status: 'open' });

    const tracker = new CompositionTracker('workspace');
    tracker.noteEditorEdit(9);
    tracker.noteEditorEdit(120);

    expect((await committedMetrics(tracker)).typed_chars).toBe(129);
  });

  it('ignores deletions and nonsense', async () => {
    createCompositionSession.mockResolvedValue({ id: 'sess-3', status: 'open' });

    const tracker = new CompositionTracker('workspace');
    tracker.noteEditorEdit(-40);
    tracker.noteEditorEdit(Number.NaN);
    tracker.noteEditorEdit(0);

    expect(createCompositionSession).not.toHaveBeenCalled();
    expect(tracker.id).toBeNull();
  });
});
