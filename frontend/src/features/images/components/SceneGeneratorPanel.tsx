import { useState, useEffect, useRef } from 'react';
import { ImageIcon, RefreshCw } from 'lucide-react';
import { generateImage } from '@/features/characterCreation/shared/api';
import type { CharacterImageRead } from '@/features/characterCreation/shared/types';
import type { Character } from '@/lib/types';
import { useAuthStore } from '@/lib/store';

const MAX_PROMPT_LENGTH = 800;

// Beta: Google (option2) is the primary "Canon" provider for everyone.
// OpenAI (option1), FLUX Pro (option3), FLUX Max (option4), and Together FLUX.2 (option5) are admin-only.
// FLUX options are text-to-image only — identity refs are not forwarded.
// Together (option5) supports URL-based refs when public HTTPS canon URLs are available.
const SHOW_PROVIDER_TOGGLE = true;

type ProviderOption = 'option1' | 'option2' | 'option3' | 'option4' | 'option5';

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
  // Beta default: Google ("Canon"). OpenAI, FLUX Pro, FLUX Max are admin-only.
  const [providerOption, setProviderOption] = useState<ProviderOption>('option2');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const isAdmin = useAuthStore((s) => !!s.user?.is_admin);

  // Guard: if a non-admin ends up on any admin-only option, snap back to Canon.
  useEffect(() => {
    const adminOnly: ProviderOption[] = ['option1', 'option3', 'option4', 'option5'];
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

  // Derive lock/anchor state from the currently selected character
  const selectedChar = characters.find((c) => c.id === selectedCharacterId) ?? null;
  const isCharacterLocked = selectedChar?.visual_locked ?? false;

  // Mirrors _parse_anchor_json on the backend: needs anchors.front.url to be non-empty.
  // Returns true/false/undefined — undefined means JSON absent (legacy; let backend try DB fallback).
  const hasIdentityAnchor: boolean | undefined = (() => {
    const raw = selectedChar?.identity_anchor_json;
    if (!raw) return undefined;
    try {
      const data = JSON.parse(raw);
      return !!(data?.anchors?.front?.url);
    } catch {
      return false;
    }
  })();

  // Guards only apply when a character is selected
  const lockedGuardActive = selectedCharacterId !== null && !isCharacterLocked;
  const anchorGuardActive = selectedCharacterId !== null && isCharacterLocked && hasIdentityAnchor === false;
  const canGenerate = prompt.trim().length > 0 && !loading && !lockedGuardActive && !anchorGuardActive;

  const handleGenerate = async () => {
    if (!canGenerate) return;
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
            OpenAI, FLUX Pro, FLUX Max are admin-only.
            FLUX options are text-to-image only — refs not forwarded. */}
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
              <>
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
                <button
                  type="button"
                  onClick={() => setProviderOption('option3')}
                  disabled={loading}
                  title="FLUX Pro — OpenRouter, admin-only, text-to-image only (refs not forwarded)"
                  className={`px-3 py-1 transition-colors ${
                    providerOption === 'option3'
                      ? 'bg-violet-700 text-white'
                      : 'bg-gray-800 text-gray-400 hover:bg-violet-900/40 hover:text-violet-300'
                  }`}
                >
                  FLUX Pro · Admin
                </button>
                <button
                  type="button"
                  onClick={() => setProviderOption('option4')}
                  disabled={loading}
                  title="FLUX Max — OpenRouter, admin-only, text-to-image only (refs not forwarded)"
                  className={`px-3 py-1 transition-colors ${
                    providerOption === 'option4'
                      ? 'bg-violet-700 text-white'
                      : 'bg-gray-800 text-gray-400 hover:bg-violet-900/40 hover:text-violet-300'
                  }`}
                >
                  FLUX Max · Admin
                </button>
                <button
                  type="button"
                  onClick={() => setProviderOption('option5')}
                  disabled={loading}
                  title="Together FLUX.2 — admin-only, URL-based refs when public HTTPS canon URLs are available"
                  className={`px-3 py-1 transition-colors ${
                    providerOption === 'option5'
                      ? 'bg-sky-700 text-white'
                      : 'bg-gray-800 text-gray-400 hover:bg-sky-900/40 hover:text-sky-300'
                  }`}
                >
                  Together · Admin
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Locked-character guard message */}
      {lockedGuardActive && (
        <p className="text-sm text-amber-400 bg-amber-950/40 border border-amber-800/40 rounded-lg px-4 py-2">
          Your character's visual identity must be locked before including them in an image.
          Complete the identity pack to unlock this option.
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
          onClick={handleGenerate}
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
    </div>
  );
}
