import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';

export default function ImageNew() {
  const [prompt, setPrompt] = useState('');
  const [stubMessage, setStubMessage] = useState('');

  const handleGenerate = () => {
    setStubMessage('Image generation wiring coming next.');
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
        <textarea
          className="textarea"
          placeholder="Describe the image you want to generate…"
          value={prompt}
          onChange={(e) => {
            setPrompt(e.target.value);
            setStubMessage('');
          }}
          rows={4}
        />
        <p className="text-xs text-gray-500">
          Be specific. No celebrity likenesses. No real people.
        </p>

        <div className="flex items-center gap-3">
          <button
            onClick={handleGenerate}
            disabled={!prompt.trim()}
            className="btn btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Generate
          </button>
          <Link to="/images" className="btn btn-secondary">
            Back
          </Link>
        </div>

        {stubMessage && (
          <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2">
            {stubMessage}
          </p>
        )}
      </div>
    </div>
  );
}
