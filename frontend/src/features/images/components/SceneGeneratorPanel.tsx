import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { ImageIcon, RefreshCw } from 'lucide-react';
import { generateImage } from '@/features/characterCreation/shared/api';
import type { CharacterImageRead } from '@/features/characterCreation/shared/types';
import type { Character } from '@/lib/types';
import type { SelectedReference } from '@/features/images/referenceKinds';
import { useAuthStore } from '@/lib/store';
import { isFounder as accountIsFounder } from '@/lib/entitlements';
import { isAdultAdjacent } from '@/features/images/adultContent';
import { computeGeneratorGuards } from '@/features/images/generatorReadiness';
import ReferencePicker from '@/features/images/components/ReferencePicker';
import UploadImageButton from '@/features/images/components/UploadImageButton';
import { useGenerationJob } from '@/features/images/useGenerationJob';

const MAX_PROMPT_LENGTH = 800;

// Beta: Google (option2) is the primary "Canon" provider for everyone.
// OpenAI (option1) is admin-only, internal testing.
// The experimental FLUX/Together providers (option3/4/5) remain on the backend
// but are intentionally hidden from this selector — they did not solve canon
// consistency and only cluttered the UI. Do not re-expose without a decision.
const SHOW_PROVIDER_TOGGLE = true;

type ProviderOption = 'option1' | 'option2' | 'option3' | 'option4' | 'option5' | 'option6';

interface Props {
  characters: Character[];
  onGenerated: (image: CharacterImageRead) => void;
  /** Called with true when a request starts, false when it settles. */
  onGeneratingChange?: (generating: boolean) => void;
  /** When true, generates wide-banner cover images (kind=cover) instead of standard images. */
  isCover?: boolean;
  /** Pre-select this character on first load (onboarding nudge). */
  initialCharacterId?: number;
  /** Pre-fill the prompt textarea on first load (onboarding nudge). */
  initialPrompt?: string;
  /**
   * Keep the panel's character in step with the page's character selection.
   *
   * Distinct from `initialCharacterId`, which fires once. The founder workflow
   * is "pick a character, then work on it" — having to pick the same character
   * twice, once for the library and again in the panel, is a step for nothing
   * and is worse on a tablet than on a laptop. Null (an "all characters" view)
   * leaves the panel's own selection alone.
   */
  followCharacterId?: number | null;
}

export default function SceneGeneratorPanel({
  characters,
  onGenerated,
  onGeneratingChange,
  isCover = false,
  initialCharacterId,
  initialPrompt,
  followCharacterId,
}: Props) {
  const [prompt, setPrompt] = useState(initialPrompt ?? '');
  // null = "No character"; number = character id
  const [selectedCharacterId, setSelectedCharacterId] = useState<number | null>(null);
  const initialCharacterIdRef = useRef(initialCharacterId);
  // Beta default: Google ("Canon"). OpenAI (option1) is admin-only.
  const [providerOption, setProviderOption] = useState<ProviderOption>('option2');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  // Adult-adjacent soft nudge — advisory only, does not block generation.
  const [showAdultNudge, setShowAdultNudge] = useState(false);

  const user = useAuthStore((s) => s.user);
  const isAdmin = !!user?.is_admin;
  const isFounder = accountIsFounder(user);
  const navigate = useNavigate();

  // ── Founder workflow state ────────────────────────────────────────
  // Hand-picked references, and a token bumped after an upload so the picker
  // refetches and the new image is immediately selectable.
  const [references, setReferences] = useState<SelectedReference[]>([]);
  const [libraryToken, setLibraryToken] = useState(0);

  // Founders generate through the async job pipeline; everyone else keeps the
  // original synchronous call. The reason is the request deadline, not the
  // feature set: a founder generation can carry four provider calls and outlive
  // the request, and losing it after paying is the failure this removes.
  const job = useGenerationJob(selectedCharacterId);
  const useJobs = isFounder;

  // References and uploads are character-scoped, so they need an explicitly
  // chosen character — "No character" has no image collection to draw on.
  const founderToolsVisible = isFounder && selectedCharacterId != null;

  // Re-attach to a generation still running for this character (tablet
  // reconnect, tab reopened, page reloaded). Submits nothing.
  useEffect(() => {
    if (!useJobs || selectedCharacterId == null) return;
    void job.resume();
    // job.resume is stable per character; re-running on every render would poll
    // the recovery endpoint continuously.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [useJobs, selectedCharacterId]);

  // A reference belongs to one character. Switching character must not carry a
  // stale selection across — the server would reject those ids anyway, but the
  // founder should never see another character's picks staged as their own.
  useEffect(() => {
    setReferences([]);
  }, [selectedCharacterId]);

  // Guard: if an account ends up on an option it may not use, snap back to Canon.
  // OpenAI (option1) is available to admins AND to the founder/seeder tier —
  // "OpenAI or Google" is the founder workflow. The experimental providers
  // (FLUX Pro/Max, Together, Grok) stay admin-only. Mirrors the server rule in
  // image_provider.resolve_canon_provider_option, which is what actually decides.
  useEffect(() => {
    const experimental: ProviderOption[] = ['option3', 'option4', 'option5', 'option6'];
    if (!isAdmin && experimental.includes(providerOption)) setProviderOption('option2');
    if (!isAdmin && !isFounder && providerOption === 'option1') setProviderOption('option2');
  }, [isAdmin, isFounder, providerOption]);

  // Set default selection once when characters first load
  const didInitRef = useRef(false);
  useEffect(() => {
    if (didInitRef.current || characters.length === 0) return;
    didInitRef.current = true;
    const initId = initialCharacterIdRef.current;
    if (initId != null && characters.some((c) => c.id === initId)) {
      setSelectedCharacterId(initId);
    } else if (characters.length === 1) {
      setSelectedCharacterId(characters[0].id);
    }
    // Multi-character with no initId: default to "No character" (null) — explicit selection required
  }, [characters]);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // Derive readiness guards from the currently selected character.
  // A v2 canon character (visual_locked + has_identity_canon, S24AR/S24AU.2) is
  // accepted by the backend scene route directly and is never blocked by the
  // legacy identity-anchor guard. See computeGeneratorGuards for the full rule.
  const selectedChar = characters.find((c) => c.id === selectedCharacterId) ?? null;
  const { lockedGuardActive, anchorGuardActive } = computeGeneratorGuards(
    selectedCharacterId,
    selectedChar,
  );
  // `busy` is the single truth for "a generation is in flight", whichever path
  // is running, so every disabled state and every spinner agrees.
  const busy = useJobs ? job.busy : loading;
  const canGenerate =
    prompt.trim().length > 0 && !busy && !lockedGuardActive && !anchorGuardActive;

  // Follow the page's character selection (see the prop docs). Deliberately
  // skipped while a generation is in flight: re-pointing the panel mid-run
  // would leave the founder watching progress under one character's name while
  // the image is being made for another. Null (an "all characters" view) means
  // the page has no opinion, so the panel keeps whatever it has.
  useEffect(() => {
    if (followCharacterId == null || busy) return;
    setSelectedCharacterId((current) =>
      current === followCharacterId ? current : followCharacterId,
    );
  }, [followCharacterId, busy]);

  // A completed job hands its image to the parent exactly once, then clears
  // itself so the panel returns to an idle, ready-to-generate state. The image
  // lives in the parent's library grid from that moment — which is where the
  // founder keeps or deletes it, using the controls that already exist there.
  const deliveredJobRef = useRef<string | null>(null);
  useEffect(() => {
    if (job.phase !== 'completed' || !job.job || !job.image) return;
    if (deliveredJobRef.current === job.job.job_id) return;
    deliveredJobRef.current = job.job.job_id;
    onGenerated(job.image as unknown as CharacterImageRead);
    setPrompt('');
    onGeneratingChange?.(false);
    // onGenerated identity is not stable in every caller; keying on the job id
    // above is what makes this exactly-once rather than the dependency list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.phase, job.job, job.image]);

  useEffect(() => {
    if (useJobs) onGeneratingChange?.(job.busy);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [useJobs, job.busy]);

  const handleGenerate = async (skipAdultCheck = false) => {
    if (!canGenerate) return;
    // Adult-adjacent soft nudge: surface the 18+ Studio entry once before generating.
    // Advisory only — "Continue here" re-invokes with skipAdultCheck=true.
    if (!skipAdultCheck && isAdultAdjacent(prompt)) {
      setShowAdultNudge(true);
      return;
    }
    // For "No character", route through the first character (ownership only; include_character=false)
    const routeCharacterId = selectedCharacterId ?? characters[0]?.id;
    if (!routeCharacterId) return;

    // References are character-scoped: they only travel when a character is
    // actually selected, so a "No character" generation can never smuggle them.
    const refs = founderToolsVisible ? references : [];

    if (useJobs) {
      setError('');
      await job.submit(routeCharacterId, {
        prompt: prompt.trim(),
        include_character: selectedCharacterId !== null,
        provider_option: providerOption,
        is_cover: isCover,
        reference_image_ids: refs.map((r) => r.image.id),
        reference_roles: refs.map((r) => r.role),
      });
      return;
    }

    setLoading(true);
    setError('');
    onGeneratingChange?.(true);
    try {
      const image = await generateImage(
        routeCharacterId,
        prompt.trim(),
        selectedCharacterId !== null, // include_character
        providerOption,
        isCover,
      );
      if (!mountedRef.current) return;
      onGenerated(image);
      setPrompt('');
    } catch (err) {
      if (!mountedRef.current) return;
      setError(err instanceof Error ? err.message : "We couldn't generate the image right now. Try again.");
    } finally {
      if (mountedRef.current) {
        setLoading(false);
        onGeneratingChange?.(false);
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && canGenerate) {
      e.preventDefault();
      handleGenerate();
    }
  };

  return (
    <div className="border border-edge rounded-lg bg-surface p-4 space-y-3">
      <div className="flex items-center gap-2">
        <ImageIcon className="w-4 h-4 text-gem" />
        <h3 className="text-sm font-medium text-ink-2">
          {isCover ? 'Cover Generator' : 'Image Generator'}
        </h3>
        {isCover && (
          <span className="text-xs text-ink-3 ml-1">— wide banner format</span>
        )}
      </div>

      <textarea
        className="textarea w-full"
        rows={3}
        maxLength={MAX_PROMPT_LENGTH}
        placeholder={
          isCover
            ? 'Describe a wide, cinematic scene for your profile banner…'
            : 'Describe the image you want to generate…'
        }
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={busy}
      />

      {/* Controls row */}
      <div className="flex flex-wrap items-center gap-4">
        {/* Character selector */}
        <div className="flex items-center gap-2 min-w-0">
          <label className="text-sm text-ink-2 shrink-0">Character</label>
          <select
            className="bg-surface-elevated border border-edge-md rounded-md text-sm text-ink-2 px-3 py-1.5 disabled:opacity-50 focus:outline-none focus:border-edge-md"
            value={selectedCharacterId ?? 'none'}
            onChange={(e) =>
              setSelectedCharacterId(e.target.value === 'none' ? null : Number(e.target.value))
            }
            disabled={busy}
          >
            <option value="none">No character</option>
            {characters.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>

        {/* Provider selector. Beta: Google = "Canon" (primary, everyone).
            OpenAI (option1) is admin-only, internal testing.
            The experimental FLUX/Together providers are hidden — see header note. */}
        {SHOW_PROVIDER_TOGGLE && (
          <div className="flex items-center gap-1 rounded-md border border-edge-md overflow-hidden text-xs">
            <button
              type="button"
              onClick={() => setProviderOption('option2')}
              disabled={busy}
              title="Google — the recommended Canon image provider"
              className={`px-3 py-1 transition-colors ${
                providerOption === 'option2'
                  ? 'bg-gem text-gem-ink'
                  : 'bg-surface-elevated text-ink-2 hover:bg-gem-soft hover:text-gem'
              }`}
            >
              Canon · Recommended
            </button>
            {(isAdmin || isFounder) && (
              <button
                type="button"
                onClick={() => setProviderOption('option1')}
                disabled={busy}
                title="OpenAI — available to founder accounts"
                className={`px-3 py-1 transition-colors ${
                  providerOption === 'option1'
                    ? 'bg-amber-700 text-white'
                    : 'bg-surface-elevated text-ink-2 hover:bg-amber-900/40 hover:text-amber-300'
                }`}
              >
                {isAdmin ? 'OpenAI · Admin' : 'OpenAI'}
              </button>
            )}
            {isAdmin && (
              <button
                type="button"
                onClick={() => setProviderOption('option6')}
                disabled={busy}
                title="Grok Imagine (via OpenRouter) — experimental, admin-only"
                className={`px-3 py-1 transition-colors ${
                  providerOption === 'option6'
                    ? 'bg-sky-700 text-white'
                    : 'bg-surface-elevated text-ink-2 hover:bg-sky-900/40 hover:text-sky-300'
                }`}
              >
                Grok · Admin
              </button>
            )}
          </div>
        )}
      </div>

      {/* ── Founder tools: upload + reference selection ──────────────
          Founder/seeder only, and only with a character actually chosen —
          references are that character's own images. Ordinary creators never
          see this block, and the server refuses it for them regardless. */}
      {founderToolsVisible && (
        <div className="rounded-xl border border-edge-md bg-surface-elevated/40 p-3 sm:p-4 space-y-4">
          <UploadImageButton
            characterId={selectedCharacterId}
            disabled={busy}
            onUploaded={(image) => {
              // Refresh the grid, then stage the new upload as a reference if
              // there is room — uploading one is almost always the first half of
              // "use this as a reference", and making the founder hunt for it in
              // the grid afterwards is a step for nothing.
              setLibraryToken((t) => t + 1);
              setReferences((prev) =>
                prev.length < 4 ? [...prev, { image, role: 'unspecified' }] : prev,
              );
            }}
          />
          <ReferencePicker
            characterId={selectedCharacterId}
            selected={references}
            onChange={setReferences}
            disabled={busy}
            refreshToken={libraryToken}
          />
        </div>
      )}

      {/* Locked-character guard message */}
      {lockedGuardActive && (
        <p className="text-sm text-amber-400 bg-amber-950/40 border border-amber-800/40 rounded-lg px-4 py-2">
          Complete and lock your identity pack before generating character images.
        </p>
      )}

      {/* Anchor-data guard message (character is locked but identity_anchor_json is missing) */}
      {anchorGuardActive && (
        <p className="text-sm text-amber-400 bg-amber-950/40 border border-amber-800/40 rounded-lg px-4 py-2">
          Your character's identity anchor is missing. Please regenerate and accept the identity pack from the character page.
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className={`text-xs ${prompt.length >= MAX_PROMPT_LENGTH ? 'text-red-400' : 'text-ink-3'}`}>
          {prompt.length} / {MAX_PROMPT_LENGTH}
        </span>
        <button
          // Full-width on phones so it is a comfortable thumb target; inline
          // from `sm` upward where the row has room.
          className="btn btn-primary text-sm flex items-center justify-center gap-2 w-full sm:w-auto py-3 sm:py-2"
          onClick={() => handleGenerate()}
          disabled={!canGenerate}
        >
          {busy ? (
            <>
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              Generating…
            </>
          ) : (
            <>
              <ImageIcon className="w-3.5 h-3.5" />
              {isCover ? 'Generate Cover' : 'Generate Image'}
            </>
          )}
        </button>
      </div>

      {/* Live job state. This is what makes a long generation survivable on a
          tablet: the panel keeps telling the founder it is still working, and
          re-attaches to the same job after a reconnect instead of restarting. */}
      {useJobs && busy && (
        <div className="flex items-start gap-2.5 text-sm text-ink-2 bg-gem-soft/40 border border-gem/20 rounded-lg px-4 py-3">
          <RefreshCw className="w-3.5 h-3.5 mt-0.5 shrink-0 animate-spin text-gem" />
          <div className="min-w-0">
            <p>{job.job?.progress_message || 'Starting…'}</p>
            <p className="text-xs text-ink-3 mt-0.5">
              This can take a couple of minutes. You can leave this page — the image
              will be waiting when you come back.
            </p>
          </div>
        </div>
      )}

      {/* Reference-budget report. The server never drops a reference silently;
          when it can't send one, it says which and why, and this surfaces it. */}
      {useJobs && job.phase === 'completed' && job.job?.result?.warning && (
        <p className="text-sm text-amber-400/90 bg-amber-400/10 border border-amber-800/30 rounded-lg px-4 py-2">
          {job.job.result.warning}
        </p>
      )}

      {(error || (useJobs && job.error)) && (
        <p className="text-sm text-amber-400/90 bg-amber-400/10 border border-amber-800/30 rounded-lg px-4 py-2">
          {error || job.error}
        </p>
      )}

      {/* Adult-adjacent soft nudge — advisory, does not block generation. */}
      {showAdultNudge && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
        >
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            onClick={() => setShowAdultNudge(false)}
          />
          <div className="relative z-10 w-full max-w-md bg-app border border-edge rounded-2xl shadow-2xl p-6 space-y-4">
            <h2 className="text-base font-semibold text-ink">
              Looks like adult-adjacent content
            </h2>
            <p className="text-sm leading-relaxed text-ink-2">
              This looks like adult-adjacent content. For stronger identity consistency in
              swimwear, lingerie, underwear, and mature scenes, try our upcoming 18+ Studio.
            </p>
            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                className="btn btn-secondary text-sm"
                onClick={() => {
                  setShowAdultNudge(false);
                  handleGenerate(true);
                }}
              >
                Continue here
              </button>
              <button
                type="button"
                className="btn btn-primary text-sm"
                onClick={() => {
                  setShowAdultNudge(false);
                  navigate('/studio/18-plus');
                }}
              >
                Open 18+ Studio
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
