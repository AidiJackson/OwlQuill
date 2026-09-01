// Admin Creator — experimental four-reference image workflow.
//
// A SECOND creation workflow, deliberately separate from the Image Generator on
// /images. Both exist at once so we can compare them; neither is the other's
// replacement, and this page changes nothing about how /images behaves.
//
// Founder/seeder only (see features/adminCreator/access). Ordinary creators and
// Wanderers get the same "not available" panel as an unauthenticated visitor,
// and the server independently refuses every call regardless of what renders.
//
// It reuses the existing backend wholesale: the same upload endpoint, the same
// manual-reference validation, the same image_generation_jobs async pipeline,
// the same providers. Results are ordinary CharacterImage rows for the selected
// character, so generated output lands in Ficshon's existing media system and
// appears in the Image Library like anything else — there is no separate store.
//
// The ONE behavioural difference is reference_mode="deliberate" on submission:
// the provider receives the four cards and the prompt, and nothing else. Canon
// is not compiled into the prompt and no canon reference image is routed in.
// The selected character is an ownership and storage destination — it decides
// which library the references come from and where the result is saved, not what
// the image looks like. /images sends no mode and is unchanged.
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, FlaskConical, ImageIcon, RefreshCw } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import { useAuthStore } from '@/lib/store';
import type { Character } from '@/lib/types';
import { canUseAdminCreator } from '@/features/adminCreator/access';
import {
  character1ReuseTarget,
  emptySlots,
  fillSlot,
  firstEmptySlot,
  toSubmission,
  type ReferenceSlots,
} from '@/features/adminCreator/referenceSlots';
import { derivePassIntent } from '@/features/adminCreator/passIntent';
import { MAX_REFERENCES } from '@/features/images/referenceKinds';
import ReferenceCardBoard from '@/features/adminCreator/components/ReferenceCardBoard';
import ResultLightbox from '@/features/adminCreator/components/ResultLightbox';
import {
  // The draft deliberately OUTLIVES a generation: iterating on the same board
  // is the normal next move, so nothing here clears it. It is replaced when the
  // founder changes the board, and scoped per character so it cannot leak.
  clearJobPointer,
  defaultStore,
  loadDraft,
  loadJobPointer,
  providerForDraft,
  saveDraft,
  saveJobPointer,
} from '@/features/adminCreator/draftStorage';
import { useGenerationJob } from '@/features/images/useGenerationJob';

const MAX_PROMPT_LENGTH = 800;

// Canon (Google) is the primary provider; OpenAI is the other half of the
// founder workflow. The experimental FLUX/Together options stay off this
// surface — they did not solve canon consistency and only add noise to a
// comparison test. The server re-resolves the option regardless.
const PROVIDERS = [
  { value: 'option2', label: 'Canon · Google', hint: 'Recommended' },
  { value: 'option1', label: 'OpenAI', hint: 'Founder testing' },
] as const;

type ProviderOption = (typeof PROVIDERS)[number]['value'];

/** What a board shows before anything is chosen, and what a character with no
 *  draft of its own falls back to. */
const DEFAULT_PROVIDER: ProviderOption = 'option2';

function isProviderOption(value: string): value is ProviderOption {
  return PROVIDERS.some((p) => p.value === value);
}

export default function AdminCreator() {
  const user = useAuthStore((s) => s.user);
  const allowed = canUseAdminCreator(user);

  const [characters, setCharacters] = useState<Character[]>([]);
  const [characterId, setCharacterId] = useState<number | null>(null);
  const [slots, setSlots] = useState<ReferenceSlots>(emptySlots);
  const [libraryToken, setLibraryToken] = useState(0);
  const [prompt, setPrompt] = useState('');
  const [providerOption, setProviderOption] = useState<ProviderOption>(DEFAULT_PROVIDER);
  const [error, setError] = useState('');
  const [lightboxOpen, setLightboxOpen] = useState(false);
  // Which role the founder is placing, while they choose a card to put it in.
  // Non-null only when every card was already occupied — see
  // handleUseAsCharacter1.
  const [pendingReuse, setPendingReuse] = useState<'character_1' | 'unspecified' | null>(null);
  // True when the result on screen finished while the page was away, rather
  // than one the founder watched complete. Worth saying out loud: it explains
  // an image appearing that this visit did not appear to produce.
  const [recovered, setRecovered] = useState(false);

  const job = useGenerationJob(characterId);
  const mountedRef = useRef(true);
  const store = useRef(defaultStore()).current;
  // Guards the draft writer below. Without it, the restore pass and the
  // switch-character reset would each be written straight back to storage
  // before the restored values had landed, wiping the very draft being loaded.
  const draftReadyFor = useRef<number | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!allowed) return;
    apiClient
      .getCharacters()
      .then((chars) => {
        if (!mountedRef.current) return;
        setCharacters(chars);
        if (chars.length === 1) setCharacterId(chars[0].id);
      })
      .catch(() => {
        if (mountedRef.current) setError('Could not load your characters.');
      });
  }, [allowed]);

  // A reference belongs to one character. Switching must never carry a board
  // across — the server would reject those ids anyway, and seeing another
  // character's picks staged as this one's is worse than losing them. Each
  // character instead gets ITS OWN stored draft back, or a clean board.
  //
  // The provider is part of that draft, not a tool-wide preference: a character
  // with no draft resets to the default rather than inheriting the previous
  // character's choice, which would otherwise be persisted straight into the
  // new character's draft by the writer below.
  useEffect(() => {
    draftReadyFor.current = null;
    if (characterId == null) {
      setSlots(emptySlots());
      setPrompt('');
      setProviderOption(DEFAULT_PROVIDER);
      return;
    }
    const draft = loadDraft(store, characterId);
    setSlots(draft ? draft.slots : emptySlots());
    setPrompt(draft?.prompt ?? '');
    setProviderOption(
      providerForDraft(draft, isProviderOption, DEFAULT_PROVIDER) as ProviderOption,
    );
    draftReadyFor.current = characterId;
  }, [characterId, store]);

  // Persist the working board. Runs after the restore above has claimed this
  // character, so a reload can never overwrite the draft it is restoring.
  useEffect(() => {
    if (characterId == null || draftReadyFor.current !== characterId) return;
    saveDraft(store, characterId, { slots, prompt, providerOption });
  }, [characterId, slots, prompt, providerOption, store]);

  // Re-attach to the generation THIS session submitted (tab reloaded, tablet
  // reconnect, page lost mid-run). Submits nothing, and spends nothing.
  //
  // The exact job id is used in preference to "the latest job for this
  // character": it cannot adopt a generation this session did not start, and —
  // unlike job.resume() — it restores a job that finished while the page was
  // gone. That is the whole point here: on 2026-08-22 two paid results were
  // completed and saved while the tab was away, and there was no way back to
  // them. resume() is kept as the fallback for an in-flight job submitted
  // before this pointer existed; its /images semantics are unchanged.
  useEffect(() => {
    if (!allowed || characterId == null) return;
    const pointer = loadJobPointer(store, characterId);
    if (pointer) {
      void job.resumeJob(characterId, pointer.jobId).then((found) => {
        if (!mountedRef.current) return;
        // A pointer the server no longer recognises is dead weight; drop it so
        // it cannot keep failing on every remount.
        if (!found) {
          clearJobPointer(store);
          return;
        }
        if (found.status === 'completed' || found.status === 'failed') setRecovered(true);
      });
      return;
    }
    void job.resume();
    // The job helpers are stable per character; re-running every render would
    // poll the recovery endpoint continuously.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowed, characterId]);

  if (!allowed) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center space-y-3">
        <h1 className="text-lg font-medium text-ink">Not available</h1>
        <p className="text-sm text-ink-3">
          Admin Creator is an internal tool and isn&apos;t part of your account.
        </p>
        <Link to="/images" className="inline-block text-sm text-gem hover:underline">
          Go to the Image Library
        </Link>
      </div>
    );
  }

  const busy = job.busy;
  const passIntent = derivePassIntent(slots);
  // Free text is optional when the cards already state a complete operation —
  // a build, a refinement, or a pose pass. For anything else the prompt is the
  // only thing that says what is happening, so it stays required. The server
  // re-decides this independently; this only avoids offering a button that
  // would 422.
  const boardIsSelfDescribing =
    passIntent.kind === 'build' || passIntent.kind === 'refine' || passIntent.kind === 'pose';
  const canGenerate =
    (prompt.trim().length > 0 || boardIsSelfDescribing) && characterId != null && !busy;

  async function handleGenerate() {
    if (!canGenerate || characterId == null) return;
    setError('');
    // A new generation replaces the result the overlay was showing, and any
    // half-finished "which card?" choice about it goes with it.
    setLightboxOpen(false);
    setPendingReuse(null);
    setRecovered(false);
    const refs = toSubmission(slots);
    const submitted = await job.submit(characterId, {
      prompt: prompt.trim(),
      // The character is the owner of the result, not an input to it. Its canon
      // must not be compiled into the prompt or routed into the reference set.
      // The server enforces the same thing from reference_mode, so a stale
      // bundle sending `true` here still cannot reintroduce canon.
      include_character: false,
      provider_option: providerOption,
      reference_image_ids: refs.reference_image_ids,
      reference_roles: refs.reference_roles,
      // The flag that separates this workflow from /images: the cards and the
      // prompt are the whole brief.
      reference_mode: refs.reference_mode,
    });
    // Recorded the moment the server acknowledges the submission, before the
    // next render — losing the page between the 202 and a re-render is exactly
    // the case this exists for, and the job is already being paid for by then.
    if (submitted) saveJobPointer(store, { characterId, jobId: submitted.job_id });
  }

  /** Dismiss the finished result: the pointer has done its job. */
  function handleClearResult() {
    clearJobPointer(store);
    setLightboxOpen(false);
    setPendingReuse(null);
    setRecovered(false);
    job.reset();
  }

  const resultImage = job.image;
  const warning = job.job?.result?.warning;

  /**
   * Stage the result as a reference for the next pass.
   *
   * This is the whole staged-generation loop: a generated face becomes Person A
   * and the next board refines it. It costs nothing and duplicates nothing —
   * the result is already a saved CharacterImage, so this stages its ID exactly
   * as picking it from the library would.
   *
   * The result is deliberately NOT cleared afterwards. Sending it to a card is
   * not "done with it": the founder may want it in a second card, or to keep
   * comparing it against the next pass.
   */
  function handleSendResultToCard(index: number, role: 'character_1' | 'unspecified') {
    if (!resultImage) return;
    setSlots((current) => fillSlot(current, index, resultImage, role));
    setPendingReuse(null);
  }

  /**
   * "Use as Character 1" — the common case, one tap.
   *
   * REPLACES the existing Character 1 when there is one, so an iterative
   * refinement advances the current image instead of accumulating a second and
   * third "same person" card. Appends to the first empty card only when no
   * Character 1 exists yet.
   *
   * When there is no Character 1 and no empty card there is no safe default:
   * silently overwriting one would throw away a reference the founder chose,
   * without saying which. So the board asks, and nothing moves until they name
   * the card.
   */
  function handleUseAsCharacter1() {
    const target = character1ReuseTarget(slots);
    if (target === null) {
      setPendingReuse('character_1');
      return;
    }
    handleSendResultToCard(target, 'character_1');
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      {/* Header — states plainly that this is the experimental workflow, and
          offers the way back to the one that is not. */}
      <div className="space-y-3">
        <Link
          to="/images"
          className="inline-flex items-center gap-1.5 text-xs text-ink-3 hover:text-ink transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Image Library
        </Link>
        <div className="flex items-start gap-3">
          <FlaskConical className="w-5 h-5 text-gem shrink-0 mt-0.5" />
          <div>
            <h1 className="text-lg font-medium text-ink">Admin Creator</h1>
            <p className="text-sm text-ink-3 mt-0.5">
              Experimental four-reference workflow. Internal founder tool — the standard
              Image Generator on{' '}
              <Link to="/images" className="text-gem hover:underline">
                /images
              </Link>{' '}
              is unchanged and still the normal way to create images.
            </p>
          </div>
        </div>
      </div>

      {/* 1 — Character */}
      <section className="rounded-xl border border-edge-md bg-surface-elevated/40 p-3 sm:p-4 space-y-2">
        <label className="text-sm font-medium text-ink-2" htmlFor="ac-character">
          Character
        </label>
        <p className="text-xs text-ink-3">
          Where the result is saved, and whose library you can pick references from. Their
          canon is not used to generate the image.
        </p>
        <select
          id="ac-character"
          className="w-full sm:w-auto bg-surface border border-edge-md rounded-lg text-sm text-ink-2 px-3 py-2 focus:outline-none focus:border-gem disabled:opacity-50"
          value={characterId ?? ''}
          disabled={busy}
          onChange={(e) => setCharacterId(e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">Select a character…</option>
          {characters.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </section>

      {/* 2 — The four reference cards */}
      <section className="rounded-xl border border-edge-md bg-surface-elevated/40 p-3 sm:p-4">
        <ReferenceCardBoard
          characterId={characterId}
          slots={slots}
          onChange={setSlots}
          disabled={busy}
          refreshToken={libraryToken}
          onUploaded={() => setLibraryToken((t) => t + 1)}
        />
      </section>

      {/* 3 — Prompt */}
      <section className="rounded-xl border border-edge-md bg-surface-elevated/40 p-3 sm:p-4 space-y-2">
        <label className="text-sm font-medium text-ink-2" htmlFor="ac-prompt">
          Prompt{' '}
          <span className="font-normal text-ink-3">
            {boardIsSelfDescribing ? '· optional' : '· required'}
          </span>
        </label>
        <textarea
          id="ac-prompt"
          rows={4}
          maxLength={MAX_PROMPT_LENGTH}
          value={prompt}
          disabled={busy}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={
            boardIsSelfDescribing
              ? 'Optional — scene, lighting or expression. The cards already describe the edit.'
              : 'Describe the image you want…'
          }
          className="w-full bg-surface border border-edge-md rounded-lg text-sm text-ink-2 px-3 py-2 focus:outline-none focus:border-gem disabled:opacity-50"
        />
        <div className="flex items-start justify-between gap-3">
          {/* Says WHY it is optional, so an empty box never looks like an
              oversight the founder is about to pay for. */}
          <p className="text-xs text-ink-3">
            {boardIsSelfDescribing
              ? 'Your cards already state the change — you do not need to repeat it here.'
              : 'These cards do not say what is happening, so a prompt is needed.'}
          </p>
          <p className="text-xs text-ink-3 shrink-0">
            {prompt.length} / {MAX_PROMPT_LENGTH}
          </p>
        </div>
      </section>

      {/* 4 — Provider */}
      <section className="rounded-xl border border-edge-md bg-surface-elevated/40 p-3 sm:p-4 space-y-2">
        <span className="text-sm font-medium text-ink-2">Provider</span>
        <div className="flex flex-wrap gap-2">
          {PROVIDERS.map((p) => (
            <button
              key={p.value}
              type="button"
              onClick={() => setProviderOption(p.value)}
              disabled={busy}
              className={`rounded-xl border px-3 py-2 text-sm transition-colors disabled:opacity-50 ${
                providerOption === p.value
                  ? 'border-gem text-ink'
                  : 'border-edge-md text-ink-3 hover:text-ink hover:border-gem/40'
              }`}
            >
              {p.label}
              <span className="block text-[11px] text-ink-3">{p.hint}</span>
            </button>
          ))}
        </div>
      </section>

      {/* 5 — What this pass will do. Derived from the roles, never chosen:
          the cards are the source of truth, and this reads them back so the
          founder can see which pass they have assembled BEFORE spending one. */}
      {passIntent.kind !== 'empty' && (
        <div className="rounded-xl border border-edge-md bg-surface-elevated/40 px-4 py-3">
          <p className="text-xs uppercase tracking-wide text-ink-3">This pass will</p>
          <p className="text-sm text-ink-2 mt-0.5">{passIntent.headline}</p>
          {passIntent.detail && <p className="text-xs text-ink-3 mt-0.5">{passIntent.detail}</p>}
        </div>
      )}

      {/* 6 — Generate */}
      <button
        type="button"
        onClick={handleGenerate}
        disabled={!canGenerate}
        className="w-full sm:w-auto flex items-center justify-center gap-2 rounded-xl bg-gem text-gem-ink px-5 py-3 text-sm font-medium transition-opacity disabled:opacity-40"
      >
        {busy ? <RefreshCw className="w-4 h-4 animate-spin" /> : <ImageIcon className="w-4 h-4" />}
        {busy ? 'Generating…' : 'Generate image'}
      </button>

      {/* 7 — Progress. The job row is the truth; this only renders it. */}
      {busy && (
        <div className="rounded-xl border border-edge-md bg-surface-elevated/40 px-4 py-3 space-y-1">
          <p className="flex items-center gap-2 text-sm text-ink-2">
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            {job.job?.progress_message || 'Starting…'}
          </p>
          {job.job?.stage && <p className="text-xs text-ink-3">Stage: {job.job.stage}</p>}
        </div>
      )}

      {(error || job.error) && (
        <div className="flex items-start justify-between gap-3 text-sm text-amber-400 bg-amber-950/40 border border-amber-800/40 rounded-lg px-4 py-2">
          <p>
            {recovered && job.phase === 'failed' && (
              <span className="block text-xs text-amber-300/80">
                This generation failed while the page was closed.
              </span>
            )}
            {error || job.error}
          </p>
          {/* A failed job's pointer must be dismissible too, or the failure
              would greet the founder on every remount. */}
          {job.phase === 'failed' && (
            <button
              type="button"
              onClick={handleClearResult}
              className="shrink-0 text-xs text-amber-300/80 hover:text-amber-200 transition-colors"
            >
              Dismiss
            </button>
          )}
        </div>
      )}

      {/* 8 — Result. An ordinary CharacterImage row: it is already in the
          character's library, so this is a confirmation view, not a store. */}
      {!busy && resultImage && (
        <section className="rounded-xl border border-edge-md bg-surface-elevated/40 p-3 sm:p-4 space-y-3">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <span className="text-sm font-medium text-ink-2">
              Result{recovered && <span className="text-ink-3 font-normal"> · recovered</span>}
            </span>
            <button
              type="button"
              onClick={handleClearResult}
              className="text-xs text-ink-3 hover:text-ink transition-colors"
            >
              Clear
            </button>
          </div>
          {recovered && (
            <p className="text-xs text-ink-3">
              This generation finished while the page was closed. It was already saved — nothing
              was charged again.
            </p>
          )}
          {warning && <p className="text-xs text-amber-400">{warning}</p>}
          {/* Click to inspect: judging a reference set needs the full image,
              not a card-sized preview. */}
          <button
            type="button"
            onClick={() => setLightboxOpen(true)}
            aria-label="View full size"
            className="block w-full max-w-md rounded-xl border border-edge-md bg-surface overflow-hidden cursor-zoom-in hover:border-gem/40 transition-colors"
          >
            <img src={resultImage.url} alt="" className="w-full block" />
          </button>
          {/* Staged generation: the result becomes the input to the next pass
              without leaving this page. It is already a saved CharacterImage,
              so this stages its id — no bytes are copied and no new row is
              created. */}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button
              type="button"
              onClick={handleUseAsCharacter1}
              className="rounded-lg border border-gem/40 px-3 py-1.5 text-xs text-ink-2 hover:text-ink hover:border-gem transition-colors"
            >
              Use as Character 1
            </button>
            <button
              type="button"
              onClick={() => setPendingReuse('unspecified')}
              className="rounded-lg border border-edge-md px-3 py-1.5 text-xs text-ink-3 hover:text-ink hover:border-gem/40 transition-colors"
            >
              Send to card…
            </button>
          </div>

          {/* Explicit target choice. Reached whenever the founder asked for a
              specific card, and ALWAYS when the board is full — there is no
              safe card to overwrite by default, so nothing moves until one is
              named. */}
          {pendingReuse && (
            <div className="rounded-lg border border-edge-md bg-surface px-3 py-2 space-y-2">
              <p className="text-xs text-ink-2">
                {firstEmptySlot(slots) === null
                  ? 'All cards are full. Choose which one to replace:'
                  : 'Choose a card:'}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                {Array.from({ length: MAX_REFERENCES }, (_, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => handleSendResultToCard(i, pendingReuse)}
                    className="rounded-lg border border-edge-md px-3 py-1.5 text-xs text-ink-3 hover:text-ink hover:border-gem/40 transition-colors"
                  >
                    Card {i + 1}
                    {slots[i] && <span className="text-ink-3"> · replace</span>}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => setPendingReuse(null)}
                  className="text-xs text-ink-3 hover:text-ink transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          <p className="text-xs text-ink-3">
            Click the image to view it full size. Saved to this character&apos;s images — it
            appears in the{' '}
            <Link to="/images" className="text-gem hover:underline">
              Image Library
            </Link>{' '}
            like any other generated image.
          </p>
        </section>
      )}

      {/* Guarded on the image as well as the flag: clearing the result while the
          overlay is open must not leave an empty lightbox behind. */}
      {lightboxOpen && resultImage && (
        <ResultLightbox src={resultImage.url} onClose={() => setLightboxOpen(false)} />
      )}
    </div>
  );
}
