import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { LibraryImage } from '@/lib/types';

export default function ImageNew() {
  const [prompt, setPrompt] = useState('');
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<LibraryImage | null>(null);

  const handleGenerate = async () => {
    setGenerating(true);
    setError('');
    setResult(null);
    try {
      const image = await apiClient.generateLibraryImage(prompt.trim());
      setResult(image);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Generation failed');
    } finally {
      setGenerating(false);
    }
  };

  const handleGenerateAnother = () => {
    setResult(null);
    setError('');
  };

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <div className="border-b border-gray-800 bg-gray-900/50">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link to="/images" className="text-gray-400 hover:text-gray-200 transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <span className="text-sm font-medium text-gray-300">Generate image</span>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-6 space-y-4">
        {result ? (
          <>
            <div className="rounded-lg border border-gray-800 overflow-hidden bg-gray-900 max-w-xs">
              <img
                src={result.url}
                alt={result.prompt_summary || 'Generated image'}
                className="w-full aspect-[2/3] object-cover"
              />
            </div>
            <p className="text-sm text-gray-300">Image saved to your library.</p>
            <div className="flex items-center gap-3">
              <button onClick={handleGenerateAnother} className="btn btn-primary text-sm">
                Generate another
              </button>
              <Link to="/images" className="btn btn-secondary text-sm">
                Back to Images
              </Link>
            </div>
          </>
        ) : (
          <>
            <textarea
              className="textarea"
              placeholder="Describe the image you want to generate…"
              value={prompt}
              onChange={(e) => {
                setPrompt(e.target.value);
                setError('');
              }}
              maxLength={200}
              rows={4}
              disabled={generating}
            />
            <div className="flex items-center justify-between">
              <p className="text-xs text-gray-500">
                Be specific. No celebrity likenesses. No real people.
              </p>
              <span className="text-xs text-gray-500">{prompt.length}/200</span>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={handleGenerate}
                disabled={!prompt.trim() || generating}
                className="btn btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {generating ? 'Generating…' : 'Generate'}
              </button>
              <Link to="/images" className="btn btn-secondary">
                Back
              </Link>
            </div>

            {error && (
              <p className="text-sm text-red-400 bg-red-400/10 rounded-lg px-4 py-2">
                {error}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
