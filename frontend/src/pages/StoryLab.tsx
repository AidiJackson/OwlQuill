import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import StoryLabEngine from '@/features/storylab/StoryLabEngine';

type Mode = null | 'collaborate';

export default function StoryLab() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>(null);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">

      {/* Header + mode selector (always visible) */}
      <div className="max-w-3xl w-full mx-auto px-4 pt-10 pb-6 md:pt-12 md:pb-8">
        <div className="mb-8">
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
              Direction chips, pacing, tone, and AI-guided continuations — all in one view.
            </p>
          </button>
        </div>
      </div>

      {/* Collaborate engine — full-width below selector */}
      {mode === 'collaborate' && (
        <div className="flex-1 flex flex-col border-t border-gray-800/60 min-h-0">
          <StoryLabEngine />
        </div>
      )}

    </div>
  );
}
