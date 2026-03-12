import { useState, useEffect, useRef } from 'react';
import { ImageIcon, RefreshCw } from 'lucide-react';
import { generateImage } from '@/features/characterCreation/shared/api';
import type { CharacterImageRead } from '@/features/characterCreation/shared/types';

const MAX_PROMPT_LENGTH = 800;

// B17: Set to false to hide the provider toggle (revert to Option 1 / OpenAI only).
const SHOW_PROVIDER_TOGGLE = true;

interface Props {
  characterId: number;
  /** Whether the character's visual identity is locked. Required for include_character. */
  isCharacterLocked: boolean;
  onGenerated: (image: CharacterImageRead) => void;
  /** Called with true when a request starts, false when it settles. */
  onGeneratingChange?: (generating: boolean) => void;
}

export default function SceneGeneratorPanel({
  characterId,
  isCharacterLocked,
  onGenerated,
  onGeneratingChange,
}: Props) {
  const [prompt, setPrompt] = useState('');
  const [includeCharacter, setIncludeCharacter] = useState(false);
  const [providerOption, setProviderOption] = useState<'option1' | 'option2'>('option1');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // Guard: include_character requires a locked character
  const lockedGuardActive = includeCharacter && !isCharacterLocked;
  const canGenerate = prompt.trim().length > 0 && !loading && !lockedGuardActive;

  const handleGenerate = async () => {
    if (!canGenerate) return;
    setLoading(true);
    setError('');
    onGeneratingChange?.(true);
    try {
      const image = await generateImage(
        characterId,
        prompt.trim(),
        includeCharacter,
        providerOption,
      );
      if (!mountedRef.current) return;
      onGenerated(image);
      setPrompt('');
    } catch {
      if (!mountedRef.current) return;
      setError("We couldn't generate the image right now. Try again.");
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
        <h3 className="text-sm font-medium text-gray-300">Image Generator</h3>
      </div>

      <textarea
        className="textarea w-full"
        rows={3}
        maxLength={MAX_PROMPT_LENGTH}
        placeholder="Describe the image you want to generate…"
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={loading}
      />

      {/* Controls row */}
      <div className="flex flex-wrap items-center gap-4">
        {/* Include character checkbox */}
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            className="w-4 h-4 accent-emerald-500"
            checked={includeCharacter}
            onChange={(e) => setIncludeCharacter(e.target.checked)}
            disabled={loading}
          />
          <span className="text-sm text-gray-300">Include this character in the image</span>
        </label>

        {/* Provider toggle (Option 1 / Option 2) — easy to remove for production */}
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
              Option 1
            </button>
            <button
              type="button"
              onClick={() => setProviderOption('option2')}
              disabled={loading}
              className={`px-3 py-1 transition-colors ${
                providerOption === 'option2'
                  ? 'bg-emerald-700 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              Option 2
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
              Generate Image
            </>
          )}
        </button>
      </div>

      {error && (
        <p className="text-sm text-gray-400 bg-gray-800/60 rounded-lg px-4 py-2">
          {error}
        </p>
      )}
    </div>
  );
}
