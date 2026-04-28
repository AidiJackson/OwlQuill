import { useState, useEffect, useRef } from 'react';
import { ImageIcon, RefreshCw } from 'lucide-react';
import { generateImage } from '@/features/characterCreation/shared/api';
import type { CharacterImageRead } from '@/features/characterCreation/shared/types';
import type { Character } from '@/lib/types';

const MAX_PROMPT_LENGTH = 800;

// B17: Set to false to hide the provider toggle (revert to Option 1 / OpenAI only).
const SHOW_PROVIDER_TOGGLE = true;

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
  const [providerOption, setProviderOption] = useState<'option1' | 'option2'>('option1');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

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

        {/* Mode toggle (Studio / Cinematic) — easy to remove for production */}
        {SHOW_PROVIDER_TOGGLE && (
          <div className="flex items-center gap-1 rounded-md border border-gray-700 overflow-hidden text-xs">
            <button
              type="button"
              onClick={() => setProviderOption('option1')}
              disabled={loading}
              className={`px-3 py-1 transition-colors ${
                providerOption === 'option1'
                  ? 'bg-emerald-700 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              Studio
            </button>
            <button
              type="button"
              onClick={() => setProviderOption('option2')}
              disabled={loading}
              className={`px-3 py-1 transition-colors ${
                providerOption === 'option2'
                  ? 'bg-purple-700 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-purple-900/40 hover:text-purple-300'
              }`}
            >
              Cinematic
            </button>
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
