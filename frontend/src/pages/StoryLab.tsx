import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

type Mode = null | 'collaborate';

export default function StoryLab() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>(null);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <div className="max-w-3xl mx-auto px-4 py-12 md:py-16">

        {/* Header */}
        <div className="mb-10">
          <h1 className="text-3xl font-semibold tracking-tight text-gray-100">StoryLab</h1>
          <p className="mt-2 text-gray-400 text-sm">
            Your narrative workspace. Write solo or let the AI direct the next beat.
          </p>
        </div>

        {/* Mode selector */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Solo Write */}
          <button
            type="button"
            onClick={() => navigate('/workspace')}
            className="group text-left p-6 rounded-2xl border border-gray-800 bg-gray-900/50 hover:border-gray-700 hover:bg-gray-900/80 transition-all"
          >
            <div className="mb-3 text-2xl select-none">✍️</div>
            <p className="font-semibold text-gray-100 text-base mb-1">Solo Write</p>
            <p className="text-sm text-gray-500 leading-relaxed">
              Open WriteSpace and write at your own pace. Full editor, no AI in the loop.
            </p>
          </button>

          {/* Collaborate with AI */}
          <button
            type="button"
            onClick={() => setMode(mode === 'collaborate' ? null : 'collaborate')}
            className={`group text-left p-6 rounded-2xl border transition-all ${
              mode === 'collaborate'
                ? 'border-emerald-500/50 bg-emerald-900/20'
                : 'border-gray-800 bg-gray-900/50 hover:border-gray-700 hover:bg-gray-900/80'
            }`}
          >
            <div className="mb-3 text-2xl select-none">🤝</div>
            <p className="font-semibold text-gray-100 text-base mb-1">Collaborate with AI</p>
            <p className="text-sm text-gray-500 leading-relaxed">
              Use StoryLab to guide the narrative — direction chips, pacing, tone, and AI continuations.
            </p>
          </button>
        </div>

        {/* Collaborate placeholder panel */}
        {mode === 'collaborate' && (
          <div className="mt-6 rounded-2xl border border-emerald-800/40 bg-emerald-900/10 p-6 space-y-3">
            <p className="text-xs font-semibold text-emerald-400 uppercase tracking-wide">
              Collaborate mode
            </p>
            <p className="text-sm text-gray-400 leading-relaxed">
              AI-guided story continuation is available inside WriteSpace via the StoryLab sidebar.
              Open your story there to access direction chips, pacing controls, and the generate panel.
            </p>
            <button
              type="button"
              onClick={() => navigate('/workspace')}
              className="mt-2 inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white text-sm font-medium transition"
            >
              Open WriteSpace
            </button>
          </div>
        )}

      </div>
    </div>
  );
}
