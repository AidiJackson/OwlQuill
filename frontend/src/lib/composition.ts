/**
 * Composition sessions — the client half of Ficshon's editor session model.
 *
 * A session tells the server that someone is writing on a surface, and reports
 * counters about how the text arrived. Provenance is the first consumer;
 * autosave, revision history and writing analytics are expected to reuse the
 * same session (the server row has slots for all three).
 *
 * ## The clipboard is never read
 *
 * This module distinguishes typed text from pasted text **without touching
 * clipboard contents**. `clipboardData.getData()` is never called — not to
 * measure length, not to hash, not for anything. Insert sizes are derived by
 * diffing the textarea's own `value.length` across the `beforeinput` / `input`
 * pair, so the only thing observed is how much the field grew.
 *
 * Everything reported is an integer. There is no code path here that can send
 * text anywhere.
 */
import { apiClient } from './apiClient';
import type { CompositionMetrics } from './types';

export type { CompositionMetrics };

export type CompositionSurface =
  | 'commons_composer'
  | 'realm_composer'
  | 'workspace'
  | 'story_space'
  | 'comment'
  | 'scene';

/** Text arriving in chunks no larger than this counts as typing, when nothing
 *  better is known. Two, not one, so a dead-key accent is not read as a paste. */
const TYPING_CHUNK_MAX = 2;

/** Signals that name an insertion outright. A clipboard or drag-and-drop
 *  operation always produces one of these (or a `paste`/`drop` event). */
const INSERTION_INPUT_TYPES = new Set([
  'insertFromPaste',
  'insertFromPasteAsQuotation',
  'insertFromDrop',
  // Autocomplete, autofill and spellcheck replacement. Not typing: the text
  // came from a list, not from the writer.
  'insertReplacementText',
]);

/**
 * Input types the browser emits for **keyboard composition** — an IME, a
 * gesture keyboard, autocorrect-as-you-type.
 *
 * These are typing. They arrive in chunks larger than a keystroke because that
 * is how the keyboard works, not because the text came from anywhere else, and
 * no clipboard operation can produce them.
 */
const COMPOSITION_INPUT_TYPES = new Set([
  'insertCompositionText',
  'insertFromComposition',
]);

/**
 * Undo and redo. Counted as neither typed nor inserted.
 *
 * Redo replays an edit this same field already saw, and whatever those
 * characters were the first time — typed or pasted — they were counted then.
 * Counting them again attributes them twice, and the old rule counted the
 * replay as an *insertion*: typing "hello world", pressing undo and pressing
 * redo produced 11 typed characters and 6 inserted ones for a post of 11
 * characters, which is an external ratio of 55% and a "Created elsewhere"
 * badge on text the writer typed a moment earlier.
 *
 * Skipping them cannot launder a paste: the paste was already counted as
 * inserted, and undo does not decrement it.
 */
const HISTORY_INPUT_TYPES = new Set(['historyUndo', 'historyRedo']);

/** True for an undo/redo, which is counted as neither typed nor inserted.
 *  See :data:`HISTORY_INPUT_TYPES` for why. */
export function isHistoryEdit(inputType: string): boolean {
  return HISTORY_INPUT_TYPES.has(inputType);
}

/**
 * Decide whether a growth of the field was typed or inserted.
 *
 * Pure, and exported so the rule is testable without a DOM: it is the one place
 * where "was this typed?" is actually answered, and getting it wrong in either
 * direction mislabels real writing.
 *
 * ## Why composition is exempt from the size rule
 *
 * A size threshold alone says "more than two characters at once is not
 * typing", and on a phone that is simply false. Android gesture typing commits
 * a whole word per swipe; a Japanese or Chinese IME commits a whole phrase.
 * Under the size rule, a post swiped out on a phone reported ~100% inserted
 * and published as "Created elsewhere" — the writer typed every word of it,
 * on the keyboard their device gave them.
 *
 * Exempting composition opens no hole. The browser reports composition input
 * types only for keyboard composition; a paste always arrives as a `paste`
 * event or an `insertFromPaste`, both of which are checked first and win.
 */
export function isInsertion(input: {
  inputType: string;
  delta: number;
  recentPaste: boolean;
  /** True while the field is between `compositionstart` and `compositionend`. */
  inComposition?: boolean;
}): boolean {
  // Explicit insertion signals outrank everything, including composition — a
  // paste made while an IME is active is still a paste.
  if (input.recentPaste || INSERTION_INPUT_TYPES.has(input.inputType)) return true;

  // Keyboard composition: typing, whatever the chunk size.
  if (COMPOSITION_INPUT_TYPES.has(input.inputType) || input.inComposition) return false;

  // Bulk text with no paste signal and no composition (autocomplete,
  // extensions). Counting it as typing would be the generous reading; it is
  // not the honest one.
  return input.delta > TYPING_CHUNK_MAX;
}

/** A `paste`/`drop` event within this window attributes the next input to an
 *  insertion, for browsers whose `beforeinput` omits `inputType`. */
const PASTE_ATTRIBUTION_MS = 60;

/** How long after `compositionend` an input is still attributed to that
 *  composition. Browsers differ on whether the committing `input` fires before
 *  or after the end event. */
const COMPOSITION_ATTRIBUTION_MS = 60;

const HANDOFF_KEY = 'ficshon.composition.handoff';

/**
 * Record that a draft is being carried to another composer inside Ficshon —
 * WriteSpace's copy button is the case that exists today.
 *
 * Only the session id travels. The draft text goes to the clipboard as it
 * always did, and the server never sees it, hashes it, or learns its length
 * from us; all the handoff does is let the next composer say "this insertion
 * continues that session", which the server then bounds by what the parent
 * session was independently observed to have typed.
 */
export function markInternalHandoff(sessionId: string | null): void {
  if (!sessionId) return;
  try {
    sessionStorage.setItem(HANDOFF_KEY, sessionId);
  } catch {
    /* private mode — the paste simply reads as external, which is honest */
  }
}

function takeHandoff(): string | undefined {
  try {
    const id = sessionStorage.getItem(HANDOFF_KEY);
    if (id) sessionStorage.removeItem(HANDOFF_KEY);
    return id || undefined;
  } catch {
    return undefined;
  }
}

/**
 * Adopt only the counters this module defines.
 *
 * The server's session row carries an open JSON slot shared with autosave and
 * analytics; taking it wholesale would let an unrelated key become a metric.
 */
function adoptMetrics(raw: Partial<CompositionMetrics> | undefined): CompositionMetrics {
  const base = emptyMetrics();
  if (!raw) return base;
  for (const key of Object.keys(base) as (keyof CompositionMetrics)[]) {
    const value = raw[key];
    if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
      base[key] = Math.floor(value);
    }
  }
  return base;
}

function emptyMetrics(): CompositionMetrics {
  return {
    typed_chars: 0,
    inserted_chars: 0,
    internal_insert_chars: 0,
    largest_insertion: 0,
    insertion_count: 0,
    edit_duration_ms: 0,
  };
}

/**
 * Tracks one editing session on one field.
 *
 * Lifecycle: `attach()` a textarea, write, then `commit()` before submitting —
 * it flushes the counters and returns the session id to include in the create
 * payload. `reset()` starts a fresh session for the next message, which is what
 * keeps a session single-use and therefore unusable for replay.
 */
export class CompositionTracker {
  private sessionId: string | null = null;
  private opening: Promise<string | null> | null = null;
  private metrics = emptyMetrics();
  private startedAt = 0;
  private lastPasteAt = 0;
  /** `compositionend` timestamp. The final `input` of a composition can land
   *  just after the end event, so the flag is a short window rather than a
   *  boolean — the same shape as the paste attribution above, for the same
   *  reason: browsers disagree on the ordering. */
  private lastCompositionEndAt = 0;
  private composing = false;
  private hasHandoff = false;
  private pending: { kind: string; prevLength: number; selectionLength: number } | null = null;
  private el: HTMLTextAreaElement | HTMLInputElement | null = null;
  private detach: (() => void) | null = null;

  constructor(
    private surface: CompositionSurface,
    /** Mutable: a composer often learns its target (realm, channel) after mount.
     *  Read at session-open time, not at construction. */
    public options: { targetKind?: string; targetRef?: string } = {},
  ) {}

  /** Ref callback: `<textarea ref={tracker.attach} />`. */
  attach = (el: HTMLTextAreaElement | HTMLInputElement | null): void => {
    if (this.el === el) return;
    this.detach?.();
    this.detach = null;
    this.el = el;
    if (!el) return;

    // Native listeners rather than React synthetic ones: `beforeinput` is where
    // `inputType` lives, and React's synthetic version of it has been
    // inconsistent across versions and browsers.
    const onBeforeInput = (event: Event) => {
      const e = event as InputEvent;
      const target = e.target as HTMLTextAreaElement | null;
      if (!target) return;
      this.pending = {
        kind: e.inputType || '',
        prevLength: target.value.length,
        selectionLength: Math.abs(
          (target.selectionEnd ?? 0) - (target.selectionStart ?? 0),
        ),
      };
    };

    const onInput = (event: Event) => {
      const target = event.target as HTMLTextAreaElement | null;
      if (!target) return;
      const pending = this.pending;
      this.pending = null;

      const now = Date.now();
      if (!this.startedAt) this.startedAt = now;
      this.metrics.edit_duration_ms = now - this.startedAt;

      // Growth of the field, accounting for whatever the input replaced. This
      // is the whole measurement — no clipboard access anywhere.
      const before = pending ? pending.prevLength - pending.selectionLength : target.value.length;
      const delta = target.value.length - before;
      if (delta <= 0) {
        void this.ensureSession();
        return;
      }

      // A redo replays characters this field already counted once. Counting
      // them again — as an insertion, which is what the size rule did — is how
      // "hello world", undo, redo became a 55%-pasted post.
      if (isHistoryEdit(pending?.kind ?? '')) {
        void this.ensureSession();
        return;
      }

      const inserted = isInsertion({
        inputType: pending?.kind ?? '',
        delta,
        recentPaste: now - this.lastPasteAt < PASTE_ATTRIBUTION_MS,
        inComposition:
          this.composing || now - this.lastCompositionEndAt < COMPOSITION_ATTRIBUTION_MS,
      });

      if (inserted) {
        this.metrics.inserted_chars += delta;
        this.metrics.insertion_count += 1;
        this.metrics.largest_insertion = Math.max(this.metrics.largest_insertion, delta);
        if (this.hasHandoff) {
          // Claimed, not granted: the server credits this only up to what the
          // parent session actually typed.
          this.metrics.internal_insert_chars += delta;
        }
      } else {
        this.metrics.typed_chars += delta;
      }

      void this.ensureSession();
    };

    const onPaste = () => {
      this.lastPasteAt = Date.now();
    };

    // Gesture keyboards and IMEs commit whole words and phrases at a time.
    // Knowing a composition is in progress is what stops that from being
    // counted as text arriving from somewhere else.
    const onCompositionStart = () => {
      this.composing = true;
    };
    const onCompositionEnd = () => {
      this.composing = false;
      this.lastCompositionEndAt = Date.now();
    };

    el.addEventListener('beforeinput', onBeforeInput);
    el.addEventListener('input', onInput);
    el.addEventListener('paste', onPaste);
    el.addEventListener('compositionstart', onCompositionStart);
    el.addEventListener('compositionend', onCompositionEnd);
    el.addEventListener('drop', onPaste);

    this.detach = () => {
      el.removeEventListener('beforeinput', onBeforeInput);
      el.removeEventListener('input', onInput);
      el.removeEventListener('paste', onPaste);
      el.removeEventListener('drop', onPaste);
      el.removeEventListener('compositionstart', onCompositionStart);
      el.removeEventListener('compositionend', onCompositionEnd);
    };
  };

  /** Open the session lazily, on first input, so idle composers create nothing. */
  private ensureSession(): Promise<string | null> {
    if (this.sessionId) return Promise.resolve(this.sessionId);
    if (this.opening) return this.opening;

    const handoff = takeHandoff();
    this.hasHandoff = Boolean(handoff);

    this.opening = apiClient
      .createCompositionSession({
        surface: this.surface,
        target_kind: this.options.targetKind,
        target_ref: this.options.targetRef,
        continues_session_id: handoff,
      })
      .then((session) => {
        this.sessionId = session.id;
        return session.id;
      })
      .catch(() => {
        // A failed session must never block posting. The post simply carries no
        // evidence and is labelled unknown — no badge, which is correct.
        return null;
      })
      .finally(() => {
        this.opening = null;
      });

    return this.opening;
  }

  /** Current session id, for handing off to another composer. */
  get id(): string | null {
    return this.sessionId;
  }

  /**
   * Re-attach to the session that produced a restored draft.
   *
   * A composition session lives for the life of a component; a *draft* does
   * not. WriteSpace autosaves to localStorage and restores on mount, so
   * without this a chapter written here over two sittings arrived with no
   * typing evidence at all and was labelled "Created elsewhere" — a false
   * negative on Ficshon's own writing surface, produced by nothing worse than
   * closing a tab.
   *
   * Two outcomes, both server-bounded:
   *
   * 1. **The session is still open.** We adopt it, and adopt *the server's*
   *    counters as the baseline — not the client's memory of them, which is
   *    gone. Further typing accumulates on top. Nothing new is claimed: those
   *    characters were already observed being typed into that session.
   * 2. **It is gone, spent or too old.** We open a fresh session that
   *    *continues* the old one and declare the restored text an internal
   *    transfer. That claim is not granted: the server credits it only up to
   *    what the parent session was independently observed to have typed
   *    (`credited_internal_chars`). With no parent, the credit is zero and the
   *    draft honestly reads as created elsewhere.
   *
   * Only the id and a character count travel. The draft text stays in the
   * browser, exactly as before.
   *
   * @param sessionId       the id stored alongside the draft, if any
   * @param restoredChars   length of the restored draft
   * @returns the session id now in use, or `null` if none could be opened
   */
  resume(sessionId: string | null | undefined, restoredChars: number): Promise<string | null> {
    if (this.sessionId || this.opening) return Promise.resolve(this.sessionId);
    if (!sessionId || restoredChars <= 0) return Promise.resolve(null);

    // Held in `opening` for the whole operation, including the lookup. A fast
    // writer can type into a restored draft before the round-trip returns, and
    // `ensureSession` would otherwise open a second, empty session and then
    // have it overwritten here — losing whichever one lost the race.
    const opening = this.doResume(sessionId, restoredChars).finally(() => {
      this.opening = null;
    });
    this.opening = opening;
    return opening;
  }

  private async doResume(sessionId: string, restoredChars: number): Promise<string | null> {
    let existing: { status: string; metrics?: Partial<CompositionMetrics> } | null = null;
    try {
      existing = await apiClient.getCompositionSession(sessionId);
    } catch {
      // Unknown, foreign or deleted. Fall through to the continuation path,
      // where an unknown parent simply credits nothing.
      existing = null;
    }

    if (existing && existing.status === 'open') {
      this.sessionId = sessionId;
      // Anything typed during the lookup is already in `this.metrics`; the
      // server's totals are the baseline it sits on top of.
      const pendingTyped = this.metrics.typed_chars;
      const pendingInserted = this.metrics.inserted_chars;
      this.metrics = adoptMetrics(existing.metrics);
      this.metrics.typed_chars += pendingTyped;
      this.metrics.inserted_chars += pendingInserted;
      return this.sessionId;
    }

    try {
      const session = await apiClient.createCompositionSession({
        surface: this.surface,
        target_kind: this.options.targetKind,
        target_ref: this.options.targetRef,
        continues_session_id: sessionId,
      });
      this.sessionId = session.id;
      // Claimed as internal, granted only as far as the parent's own typing
      // supports. Counted as inserted too, so the totals still account for
      // every character the server will receive.
      this.metrics.inserted_chars += restoredChars;
      this.metrics.internal_insert_chars += restoredChars;
      this.metrics.insertion_count += 1;
      this.metrics.largest_insertion = Math.max(this.metrics.largest_insertion, restoredChars);
      return session.id;
    } catch {
      return null;
    }
  }

  /**
   * Record text the editor changed on the writer's behalf.
   *
   * WriteSpace's own tools — insert a scene break, split a long sentence,
   * apply a grammar suggestion — rewrite the textarea through React state, so
   * they fire no `input` event and no counter ever sees them. Left unrecorded,
   * a heavily edited draft reports fewer characters than the server receives
   * and trips the consistency check, which reads as "created elsewhere".
   *
   * Counted as typed because that is what it is: the writer's own text,
   * reshaped by a local editing tool, with no outside content involved. It
   * carries no more weight than a keystroke — `typed_chars` is client-attested
   * throughout and can only ever corroborate a verdict, never override AI
   * evidence.
   */
  noteEditorEdit(delta: number): void {
    if (!Number.isFinite(delta) || delta <= 0) return;
    this.metrics.typed_chars += Math.floor(delta);
    void this.ensureSession();
  }

  /**
   * Flush counters and return the id to send with the create request.
   * `undefined` when no session exists — the caller posts without evidence.
   */
  async commit(): Promise<string | undefined> {
    const id = this.sessionId ?? (await this.ensureSession());
    if (!id) return undefined;
    try {
      await apiClient.updateCompositionSession(id, this.metrics);
    } catch {
      /* the server still has whatever the last heartbeat carried */
    }
    return id;
  }

  /** Start a fresh session — call after a successful submit. */
  reset(): void {
    this.sessionId = null;
    this.metrics = emptyMetrics();
    this.startedAt = 0;
    this.lastPasteAt = 0;
    this.lastCompositionEndAt = 0;
    this.composing = false;
    this.hasHandoff = false;
    this.pending = null;
  }

  /** Remove listeners. Safe to call more than once. */
  dispose(): void {
    this.detach?.();
    this.detach = null;
    this.el = null;
  }
}
