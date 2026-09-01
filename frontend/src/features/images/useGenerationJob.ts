// Submit-and-poll driver for founder image generation.
//
// Why this exists rather than an awaited POST: the published app runs on Cloud
// Run, which enforces a request deadline, and one generation can legitimately
// spend four provider calls (first pass + two escalated face-verification
// retries + a cover retry) of up to 180s each. A tablet on mobile data loses
// that request long before it finishes — and loses it AFTER the provider has
// been paid. So the client submits an intent, then polls.
//
// The spend guarantee lives in the KEY. `idempotency_key` identifies the
// INTENT, not the request: resubmitting the same key returns the same job with
// `reused: true` and starts nothing new.
//
// A key is minted at submit and retired at exactly one moment — when the SERVER
// reports the job terminal (completed or failed). That precise rule is what
// makes the guarantee hold in both directions:
//
//   * anything short of a server verdict keeps the key, so a double-tap, a
//     dropped poll, a proxy retry, or a POST whose response was lost in transit
//     all resolve back to the same job rather than buying a second image;
//   * a server verdict retires it, so deliberately generating again is a new
//     intent and is allowed to spend.
//
// `resume()` is the reconnect story: on mount the panel asks the server for the
// latest job for this character and re-attaches to it, so an interrupted tablet
// picks the generation back up (or collects a result that landed while it was
// away) instead of starting over.
import { useCallback, useEffect, useRef, useState } from 'react';
import { apiClient } from '@/lib/apiClient';
import type { ImageGenerationJob, LibraryImage } from '@/lib/types';

// Polling cadence. Generations run in the tens of seconds at best, so a tight
// interval would be pure noise; 2.5s keeps the progress line feeling live
// without hammering the API from a phone radio.
const POLL_INTERVAL_MS = 2500;
// Client-side stop. The server reconciles a stalled job at poll time
// (HARD_TIMEOUT_S = 1800), so this only bounds a client that has been left open
// far past that; it never causes a spend.
const MAX_POLL_MS = 20 * 60 * 1000;

export type JobPhase = 'idle' | 'submitting' | 'running' | 'completed' | 'failed';

export interface GenerationSubmission {
  prompt: string;
  include_character: boolean;
  provider_option: string;
  is_cover?: boolean;
  reference_image_ids?: number[];
  reference_roles?: string[];
  // How the server should budget references against canon. OPTIONAL and unset
  // by the Image Generator, which therefore keeps the server default
  // ("augment", canon-first). Only Admin Creator sends "deliberate". The field
  // lives on the shared type because both surfaces submit through this hook;
  // leaving it out of the payload is what preserves /images behaviour.
  reference_mode?: 'augment' | 'deliberate';
}

/** Mint a fresh intent key. Only called when the founder wants a NEW image. */
export function newIntentKey(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID().replace(/-/g, '');
  // Older WebViews: still unique enough to key one account's intents, and the
  // server's unique index is the real guarantee either way.
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}

export function useGenerationJob(characterId: number | null) {
  const [phase, setPhase] = useState<JobPhase>('idle');
  const [job, setJob] = useState<ImageGenerationJob | null>(null);
  const [error, setError] = useState('');

  const mountedRef = useRef(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startedAtRef = useRef(0);
  // Held across renders so a re-render mid-flight can never mint a second key
  // and turn one intent into two paid submissions.
  const intentKeyRef = useRef<string | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const stopPolling = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const applyJob = useCallback(
    (next: ImageGenerationJob) => {
      setJob(next);
      if (next.status === 'completed' || next.status === 'failed') {
        // Terminal. Retire the intent key HERE and only here — i.e. only when
        // the SERVER has told us this intent is finished. The next submission is
        // then a genuinely new intent and is allowed to spend.
        //
        // The distinction matters: a lost POST response or a dropped poll must
        // NOT retire the key, because the server may well have created the job
        // and started paying for it. Those paths leave the key in place, so the
        // retry resolves to the same job instead of buying a second image.
        intentKeyRef.current = null;
        stopPolling();
        if (next.status === 'completed') {
          setPhase('completed');
        } else {
          setPhase('failed');
          setError(next.error_message || "We couldn't generate that image. Please try again.");
        }
      } else {
        setPhase('running');
      }
    },
    [stopPolling],
  );

  const poll = useCallback(
    (charId: number, jobId: string) => {
      timerRef.current = setTimeout(async () => {
        if (!mountedRef.current) return;
        if (Date.now() - startedAtRef.current > MAX_POLL_MS) {
          setPhase('failed');
          setError('This generation is taking longer than expected. Reload to check on it.');
          return;
        }
        try {
          const next = await apiClient.getImageGenerationJob(charId, jobId);
          if (!mountedRef.current) return;
          applyJob(next);
          if (next.status === 'queued' || next.status === 'running') poll(charId, jobId);
        } catch {
          // A dropped poll is not a failed generation — the job keeps running on
          // the server. Keep polling; the deadline above is the only stop.
          if (mountedRef.current) poll(charId, jobId);
        }
      }, POLL_INTERVAL_MS);
    },
    [applyJob],
  );

  /**
   * Re-attach to ONE known job by its public id. Submits nothing.
   *
   * Distinct from `resume()` in the two ways that matter to a caller which
   * remembered what it submitted:
   *
   *   * it asks about a SPECIFIC job rather than "the latest for this
   *     character", so it can never adopt a generation this session did not
   *     start;
   *   * it restores a TERMINAL job as well as a running one. `resume()`
   *     deliberately ignores finished jobs, because on /images a completed job
   *     from a previous session reappearing would be a surprise. A caller that
   *     persisted this exact id is in the opposite position: the result is the
   *     thing it lost, and it has already been paid for.
   *
   * Returns the job it attached to, or null. Added for Admin Creator; /images
   * does not call it and its `resume()` semantics are untouched.
   */
  const resumeJob = useCallback(
    async (charId: number, jobId: string): Promise<ImageGenerationJob | null> => {
      try {
        const found = await apiClient.getImageGenerationJob(charId, jobId);
        if (!mountedRef.current) return null;
        // The in-flight job owns its own key; a terminal one has none to own.
        intentKeyRef.current = null;
        startedAtRef.current = Date.now();
        applyJob(found);
        if (found.status === 'queued' || found.status === 'running') poll(charId, jobId);
        return found;
      } catch {
        // Best-effort, exactly as resume(): a 404 (job pruned, wrong account)
        // or an unreachable API leaves the founder no worse off than before.
        return null;
      }
    },
    [applyJob, poll],
  );

  /** Re-attach to the latest job for this character. Submits nothing. */
  const resume = useCallback(async () => {
    if (characterId == null) return;
    try {
      const { job: latest } = await apiClient.getLatestImageGenerationJob(characterId);
      if (!mountedRef.current || !latest) return;
      // Only auto-resume something still in flight. A finished job from a
      // previous session should not silently reappear as this session's result.
      if (latest.status === 'queued' || latest.status === 'running') {
        intentKeyRef.current = null; // the in-flight job owns its own key
        startedAtRef.current = Date.now();
        applyJob(latest);
        poll(characterId, latest.job_id);
      }
    } catch {
      // Recovery is best-effort: a founder who can't reach the endpoint is no
      // worse off than before, and must not be shown an error they can't act on.
    }
  }, [characterId, applyJob, poll]);

  /**
   * Submit one generation intent.
   *
   * Returns the submitted job, or null if the submission did not reach the
   * server. A caller that wants to survive losing the page needs the job's
   * public id at exactly this moment — state set here is not readable until the
   * next render, and the page may not get one. /images ignores the return value.
   */
  const submit = useCallback(
    async (charId: number, payload: GenerationSubmission): Promise<ImageGenerationJob | null> => {
      stopPolling();
      setError('');
      setPhase('submitting');
      // Reuse the key if this intent is already in flight (double-tap); mint one
      // only for a genuinely new request.
      if (!intentKeyRef.current) intentKeyRef.current = newIntentKey();
      startedAtRef.current = Date.now();
      try {
        const submitted = await apiClient.submitImageGenerationJob(charId, {
          ...payload,
          idempotency_key: intentKeyRef.current,
        });
        if (!mountedRef.current) return submitted;
        applyJob(submitted);
        if (submitted.status === 'queued' || submitted.status === 'running') {
          poll(charId, submitted.job_id);
        }
        return submitted;
      } catch (err) {
        if (!mountedRef.current) return null;
        // The key is deliberately NOT cleared. This branch includes the case
        // where the server accepted the submission and the response was lost in
        // transit — retrying with the same key re-attaches to that job rather
        // than starting a second paid one.
        setPhase('failed');
        setError(err instanceof Error ? err.message : "We couldn't start that generation.");
        return null;
      }
    },
    [applyJob, poll, stopPolling],
  );

  /**
   * Clear the finished result and retire the intent key.
   *
   * Retiring the key is what makes the NEXT generation a new intent, so this is
   * called when the founder accepts or discards a result — never mid-flight.
   */
  const reset = useCallback(() => {
    stopPolling();
    intentKeyRef.current = null;
    setJob(null);
    setPhase('idle');
    setError('');
  }, [stopPolling]);

  const image: LibraryImage | null = job?.image ?? null;
  const busy = phase === 'submitting' || phase === 'running';

  return { phase, job, image, error, busy, submit, resume, resumeJob, reset };
}
