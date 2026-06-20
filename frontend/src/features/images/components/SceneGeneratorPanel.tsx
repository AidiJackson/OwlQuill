import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { ImageIcon, RefreshCw } from 'lucide-react';
import { generateImage } from '@/features/characterCreation/shared/api';
import type { CharacterImageRead } from '@/features/characterCreation/shared/types';
import type { Character } from '@/lib/types';
import { useAuthStore } from '@/lib/store';
import { isAdultAdjacent } from '@/features/images/adultContent';
import { computeGeneratorGuards } from '@/features/images/generatorReadiness';

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
}

export default function SceneGeneratorPanel({
  characters,
  onGenerated,
  onGeneratingChange,
  isCover = false,
  initialCharacterId,
  initialPrompt,
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

  const isAdmin = useAuthStore((s) => !!s.user?.is_admin);
  const navigate = useNavigate();

  // Guard: if a non-admin ends up on any admin-only option, snap back to Canon.
  useEffect(() => {
    const adminOnly: ProviderOption[] = ['option1', 'option3', 'option4', 'option5', 'option6'];
    if (!isAdmin && adminOnly.includes(providerOption)) setProviderOption('option2');
  }, [isAdmin, providerOption]);

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
  const canGenerate = prompt.trim().length > 0 && !loading && !lockedGuardActive && !anchorGuardActive;

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
    <div className="border border-gray-800 rounded-lg bg-gray-900/50 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <ImageIcon className="w-4 h-4 text-emerald-400" />
        <h3 className="text-sm font-medium text-gray-300">
          {isCover ? 'Cover Generator' : 'Image Generator'}
        </h3>
        {isCover && (
          <span className="text-xs text-gray-500 ml-1">— wide banner format</span>
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
        disabled={loading}
      />

      {/* Controls row */}
      <div className="flex flex-wrap items-center gap-4">
        {/* Character selector */}
        <div className="flex items-center gap-2 min-w-0">
          <label className="text-sm text-gray-400 shrink-0">Character</label>
          <select
            className="bg-gray-800 border border-gray-700 rounded-md text-sm text-gray-300 px-3 py-1.5 disabled:opacity-50 focus:outline-none focus:border-gray-600"
            value={selectedCharacterId ?? 'none'}
            onChange={(e) =>
              setSelectedCharacterId(e.target.value === 'none' ? null : Number(e.target.value))
            }
            disabled={loading}
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
          <div className="flex items-center gap-1 rounded-md border border-gray-700 overflow-hidden text-xs">
            <button
              type="button"
              onClick={() => setProviderOption('option2')}
              disabled={loading}
              title="Google — the recommended Canon image provider"
              className={`px-3 py-1 transition-colors ${
                providerOption === 'option2'
                  ? 'bg-emerald-700 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-emerald-900/40 hover:text-emerald-300'
              }`}
            >
              Canon · Recommended
            </button>
            {isAdmin && (
              <button
                type="button"
                onClick={() => setProviderOption('option1')}
                disabled={loading}
                title="OpenAI — experimental, admin-only"
                className={`px-3 py-1 transition-colors ${
                  providerOption === 'option1'
                    ? 'bg-amber-700 text-white'
                    : 'bg-gray-800 text-gray-400 hover:bg-amber-900/40 hover:text-amber-300'
                }`}
              >
                OpenAI · Admin
              </button>
            )}
            {isAdmin && (
              <button
                type="button"
                onClick={() => setProviderOption('option6')}
                disabled={loading}
                title="Grok Imagine (via OpenRouter) — experimental, admin-only"
                className={`px-3 py-1 transition-colors ${
                  providerOption === 'option6'
                    ? 'bg-sky-700 text-white'
                    : 'bg-gray-800 text-gray-400 hover:bg-sky-900/40 hover:text-sky-300'
                }`}
              >
                Grok · Admin
              </button>
            )}
          </div>
        )}
      </div>

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

      <div className="flex items-center justify-between">
        <span className={`text-xs ${prompt.length >= MAX_PROMPT_LENGTH ? 'text-red-400' : 'text-gray-500'}`}>
          {prompt.length} / {MAX_PROMPT_LENGTH}
        </span>
        <button
          className="btn btn-primary text-sm flex items-center gap-2"
          onClick={() => handleGenerate()}
          disabled={!canGenerate}
        >
          {loading ? (
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

      {error && (
        <p className="text-sm text-amber-400/90 bg-amber-400/10 border border-amber-800/30 rounded-lg px-4 py-2">
          {error}
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
          <div className="relative z-10 w-full max-w-md bg-gray-950 border border-gray-800 rounded-2xl shadow-2xl p-6 space-y-4">
            <h2 className="text-base font-semibold text-gray-100">
              Looks like adult-adjacent content
            </h2>
            <p className="text-sm leading-relaxed text-gray-300">
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
