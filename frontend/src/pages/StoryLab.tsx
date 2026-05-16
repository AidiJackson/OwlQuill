import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import StoryLabEngine from '@/features/storylab/StoryLabEngine';
import CreateStoryModal from '@/features/storylab/CreateStoryModal';
import RPReplyGenerator from '@/features/storylab/RPReplyGenerator';
import { apiClient } from '@/lib/apiClient';
import type { StoryRecord } from '@/lib/types';
import { isUuidLike, deriveReadableTitle } from '@/lib/storyTitleUtils';

type Mode = null | 'collaborate' | 'rp_reply';

function storyLabel(s: StoryRecord): string {
  if (s.title && !isUuidLike(s.title)) return s.title;
  return deriveReadableTitle(s.premise);
}

export default function StoryLab() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);

  const [stories, setStories] = useState<StoryRecord[]>([]);
  const [loadingStories, setLoadingStories] = useState(true);

  useEffect(() => {
    apiClient.listStories()
      .then((s) => setStories(s))
      .catch(() => { /* non-fatal — no stories visible but app still works */ })
      .finally(() => setLoadingStories(false));
  }, []);

  function handleStoryCreated(storyId: string) {
    setShowCreateModal(false);
    navigate(`/storylab/${storyId}`);
  }

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
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {/* Create a Story */}
          <button
            type="button"
            onClick={() => setShowCreateModal(true)}
            className="group text-left p-6 rounded-2xl border border-emerald-800/40 bg-emerald-950/30 hover:border-emerald-700/60 hover:bg-emerald-950/50 transition-all"
          >
            <div className="mb-3 text-2xl select-none">✨</div>
            <p className="font-semibold text-gray-100 text-base mb-1">Create a Story</p>
            <p className="text-sm text-gray-500 leading-relaxed">
              Name it, set the world, add characters. A real story, not a session.
            </p>
          </button>

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

          {/* Roleplay Reply */}
          <button
            type="button"
            onClick={() => setMode(mode === 'rp_reply' ? null : 'rp_reply')}
            className={`group text-left p-6 rounded-2xl border transition-all ${
              mode === 'rp_reply'
                ? 'border-violet-500/50 bg-violet-900/20'
                : 'border-gray-800 bg-gray-900/50 hover:border-gray-700 hover:bg-gray-900/80'
            }`}
          >
            <div className="mb-3 text-2xl select-none">💬</div>
            <p className="font-semibold text-gray-100 text-base mb-1">Roleplay Reply</p>
            <p className="text-sm text-gray-500 leading-relaxed">
              Paste your partner's reply and generate your character's response without taking control of theirs.
            </p>
          </button>
        </div>

        {/* ── Your Stories ─────────────────────────────────────────────── */}

        {/* Loading skeleton */}
        {loadingStories && (
          <div className="mt-10">
            <div className="h-2.5 w-24 bg-gray-800/60 rounded-full animate-pulse mb-4" />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {[1, 2].map((i) => (
                <div key={i} className="h-[60px] rounded-2xl border border-gray-800/60 bg-gray-900/20 animate-pulse" />
              ))}
            </div>
          </div>
        )}

        {/* Story list */}
        {!loadingStories && stories.length > 0 && (
          <div className="mt-10">
            <h2 className="text-[11px] font-medium text-gray-600 uppercase tracking-widest mb-4">
              Your Stories
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {stories.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => navigate(`/storylab/${s.id}`)}
                  className="group text-left flex items-center gap-3 px-4 py-3.5 rounded-2xl border border-gray-800/60 bg-gray-900/20 hover:border-gray-700/70 hover:bg-gray-900/50 transition"
                >
                  <div
                    className="w-8 h-8 rounded-xl shrink-0"
                    style={{ backgroundColor: s.cover_color }}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-200 truncate group-hover:text-gray-100 transition leading-tight">
                      {storyLabel(s)}
                    </p>
                    {s.genre && (
                      <p className="text-[11px] text-gray-600 mt-0.5 capitalize leading-tight">{s.genre}</p>
                    )}
                  </div>
                  <span className="text-gray-700 group-hover:text-gray-400 transition text-base shrink-0 select-none">›</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Collaborate engine — full-width below selector */}
      {mode === 'collaborate' && (
        <div className="flex-1 flex flex-col border-t border-gray-800/60 min-h-0">
          <StoryLabEngine />
        </div>
      )}

      {/* RP Reply Generator — full-width below selector */}
      {mode === 'rp_reply' && (
        <div className="border-t border-gray-800/60">
          <RPReplyGenerator />
        </div>
      )}

      {/* Create Story modal */}
      {showCreateModal && (
        <CreateStoryModal
          onCreated={handleStoryCreated}
          onCancel={() => setShowCreateModal(false)}
        />
      )}
    </div>
  );
}
