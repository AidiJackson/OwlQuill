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

/** Text arriving in chunks no larger than this counts as typing. Two, not one,
 *  so IME commits and dead-key composition are not misread as pastes. */
const TYPING_CHUNK_MAX = 2;

/**
 * Decide whether a growth of the field was typed or inserted.
 *
 * Pure, and exported so the rule is testable without a DOM: it is the one place
 * where "was this typed?" is actually answered, and getting it wrong in either
 * direction mislabels real writing.
 */
export function isInsertion(input: {
  inputType: string;
  delta: number;
  recentPaste: boolean;
}): boolean {
  return (
    input.recentPaste ||
    input.inputType === 'insertFromPaste' ||
    input.inputType === 'insertFromDrop' ||
    input.inputType === 'insertReplacementText' ||
    // Bulk text with no paste signal (autocomplete, extensions). Counting it
    // as typing would be the generous reading; it is not the honest one.
    input.delta > TYPING_CHUNK_MAX
  );
}

/** A `paste`/`drop` event within this window attributes the next input to an
 *  insertion, for browsers whose `beforeinput` omits `inputType`. */
const PASTE_ATTRIBUTION_MS = 60;

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

      const inserted = isInsertion({
        inputType: pending?.kind ?? '',
        delta,
        recentPaste: now - this.lastPasteAt < PASTE_ATTRIBUTION_MS,
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

    el.addEventListener('beforeinput', onBeforeInput);
    el.addEventListener('input', onInput);
    el.addEventListener('paste', onPaste);
    el.addEventListener('drop', onPaste);

    this.detach = () => {
      el.removeEventListener('beforeinput', onBeforeInput);
      el.removeEventListener('input', onInput);
      el.removeEventListener('paste', onPaste);
      el.removeEventListener('drop', onPaste);
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
