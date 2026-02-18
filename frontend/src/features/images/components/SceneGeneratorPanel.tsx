import { useState } from 'react';
import { ImageIcon, RefreshCw } from 'lucide-react';
import { generateSceneImage } from '@/features/characterCreation/shared/api';
import type { CharacterImageRead } from '@/features/characterCreation/shared/types';

const MAX_PROMPT_LENGTH = 800;

interface Props {
  characterId: number;
  onGenerated: (image: CharacterImageRead) => void;
}

export default function SceneGeneratorPanel({ characterId, onGenerated }: Props) {
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const canGenerate = prompt.trim().length > 0 && !loading;

  const handleGenerate = async () => {
    if (!canGenerate) return;
    setLoading(true);
    setError('');
    try {
      const image = await generateSceneImage(characterId, prompt.trim());
      onGenerated(image);
      setPrompt('');
    } catch {
      setError("We couldn't generate the image right now. Try again.");
    } finally {
      setLoading(false);
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
        <ImageIcon className="w-4 h-4 text-owl-400" />
        <h3 className="text-sm font-medium text-gray-300">Scene Generator</h3>
      </div>

      <textarea
        className="textarea w-full"
        rows={3}
        maxLength={MAX_PROMPT_LENGTH}
        placeholder="Describe a scene with your character..."
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={loading}
      />

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
              Generating...
            </>
          ) : (
            <>
              <ImageIcon className="w-3.5 h-3.5" />
              Generate Scene
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
