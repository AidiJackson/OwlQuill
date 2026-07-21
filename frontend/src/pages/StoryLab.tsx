import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import StoryLabEngine from '@/features/storylab/StoryLabEngine';
import CreateStoryModal from '@/features/storylab/CreateStoryModal';
import RPReplyGenerator from '@/features/storylab/RPReplyGenerator';
import { apiClient } from '@/lib/apiClient';
import type { StoryRecord } from '@/lib/types';
import { isUuidLike, deriveReadableTitle } from '@/lib/storyTitleUtils';

export type Theme = 'diamond' | 'obsidian';
type Mode = null | 'collaborate' | 'rp_reply';

const RECENT_STORIES_LIMIT = 5;
const THEME_KEY = 'ficshon_storylab_theme';

function storyLabel(s: StoryRecord): string {
  if (s.title && !isUuidLike(s.title)) return s.title;
  return deriveReadableTitle(s.premise);
}

function ChevronDown({ open }: { open: boolean }) {
  return (
    <svg
      className={`w-4 h-4 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      viewBox="0 0 24 24"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
    </svg>
  );
}

export default function StoryLab() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [stories, setStories] = useState<StoryRecord[]>([]);
  const [loadingStories, setLoadingStories] = useState(true);
  const [storiesOpen, setStoriesOpen] = useState(true);

  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const stored = localStorage.getItem(THEME_KEY);
      return stored === 'obsidian' ? 'obsidian' : 'diamond';
    } catch {
      return 'diamond';
    }
  });

  useEffect(() => {
    try { localStorage.setItem(THEME_KEY, theme); } catch { /* ignore */ }
  }, [theme]);

  useEffect(() => {
    apiClient.listStories()
      .then(setStories)
      .catch(() => {})
      .finally(() => setLoadingStories(false));
  }, []);

  function handleStoryCreated(storyId: string) {
    setShowCreateModal(false);
    navigate(`/storylab/${storyId}`);
  }

  const recentStories = stories.slice(0, RECENT_STORIES_LIMIT);
  const isDiamond = theme === 'diamond';

  // ── theme-derived class tokens ─────────────────────────────────────────────
  const page = isDiamond
    ? 'min-h-screen bg-gradient-to-b from-stone-50 via-white to-stone-50 text-gray-900 flex flex-col'
    : 'min-h-screen bg-app text-ink flex flex-col';

  const heading = isDiamond ? 'text-gray-900' : 'text-ink';
  const sub = isDiamond ? 'text-gray-500' : 'text-gray-500';

  const modeCardBase = isDiamond
    ? 'group text-left p-5 rounded-2xl border bg-white shadow-sm transition-all'
    : 'group text-left p-5 rounded-2xl border transition-all';

  const modeCardIdle = isDiamond
    ? 'border-gray-200 hover:border-emerald-300 hover:shadow-md hover:bg-emerald-50/30'
    : 'border-edge bg-surface hover:border-edge-md hover:bg-surface-elevated';

  const modeCardNewStory = isDiamond
    ? 'border-emerald-200 bg-emerald-50/50 hover:border-emerald-400 hover:bg-emerald-50 shadow-sm'
    : 'border-gem/25 bg-gem-soft/60 hover:border-gem/40 hover:bg-gem-soft';

  function modeCardActive(accent: 'emerald' | 'violet') {
    if (isDiamond) {
      return accent === 'emerald'
        ? 'border-emerald-400 bg-emerald-50 shadow-md ring-1 ring-emerald-200'
        : 'border-violet-400 bg-violet-50 shadow-md ring-1 ring-violet-200';
    }
    return accent === 'emerald'
      ? 'border-gem/50 bg-gem-soft ring-1 ring-gem/25'
      : 'border-violet-500/60 bg-violet-900/20 ring-1 ring-violet-800/30';
  }

  const modeTitle = isDiamond ? 'text-gray-900' : 'text-ink';
  const modeSub = isDiamond ? 'text-gray-500' : 'text-gray-500';
  const modeActiveBadgeEmerald = isDiamond ? 'text-emerald-600' : 'text-gem';
  const modeActiveBadgeViolet = isDiamond ? 'text-violet-600' : 'text-violet-400';

  const sectionHdr = isDiamond ? 'text-gray-500' : 'text-gray-600';
  const sectionChevron = isDiamond ? 'text-gray-400' : 'text-gray-600';

  const storyCardCls = isDiamond
    ? 'group w-full text-left flex items-center gap-4 px-4 py-4 rounded-2xl border border-gray-200 bg-white shadow-sm hover:border-emerald-300 hover:shadow-md transition'
    : 'group w-full text-left flex items-center gap-4 px-4 py-4 rounded-2xl border border-edge bg-surface hover:border-edge-md hover:bg-surface-elevated transition';

  const storyTitle = isDiamond
    ? 'text-sm font-medium text-gray-800 truncate group-hover:text-gray-900 transition leading-snug'
    : 'text-sm font-medium text-ink truncate transition leading-snug';

  const storyGenre = isDiamond ? 'text-xs text-gray-400 mt-0.5 capitalize' : 'text-xs text-gray-600 mt-0.5 capitalize';
  const storyArrow = isDiamond ? 'text-gray-400 group-hover:text-emerald-500 transition' : 'text-gray-700 group-hover:text-gray-400 transition';

  const divider = isDiamond ? 'border-gray-200' : 'border-edge';
  const skeletonBg = isDiamond ? 'bg-gray-200/60' : 'bg-surface-elevated';
  const skeletonCard = isDiamond ? 'border border-gray-200 bg-gray-100/50' : 'border border-edge bg-surface';

  return (
    <div className={page}>

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="max-w-2xl w-full mx-auto px-4 pt-10 pb-6 md:pt-12 md:pb-10">

        {/* Title row + theme toggle */}
        <div className="flex items-start justify-between gap-4 mb-8">
          <div>
            <h1 className={`font-serif text-4xl font-medium tracking-[-0.02em] ${heading}`}>StoryLab</h1>
            <p className={`mt-1.5 text-sm ${sub}`}>Your narrative workspace.</p>
          </div>

          {/* Diamond / Obsidian toggle */}
          <div className={`flex items-center gap-0.5 rounded-xl border p-0.5 mt-1 shrink-0 ${isDiamond ? 'border-gray-200 bg-gray-100' : 'border-gray-800 bg-gray-900'}`}>
            <button
              type="button"
              onClick={() => setTheme('diamond')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                isDiamond
                  ? 'bg-white text-gray-900 shadow-sm ring-1 ring-gray-200'
                  : 'text-gray-600 hover:text-gray-400'
              }`}
            >
              Diamond
            </button>
            <button
              type="button"
              onClick={() => setTheme('obsidian')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                !isDiamond
                  ? 'bg-gray-800 text-gray-100 shadow-sm ring-1 ring-gray-700'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              Obsidian
            </button>
          </div>
        </div>

        {/* ── Mode selector 2×2 ─────────────────────────────────────────── */}
        <div className="grid grid-cols-2 gap-3 mb-10">

          {/* New Story */}
          <button
            type="button"
            onClick={() => setShowCreateModal(true)}
            className={`${modeCardBase} ${modeCardNewStory}`}
          >
            <p className={`font-semibold text-sm mb-1 ${modeTitle}`}>New Story</p>
            <p className={`text-xs leading-relaxed hidden sm:block ${modeSub}`}>
              Name it, set the world, add characters.
            </p>
          </button>

          {/* Solo Write */}
          <button
            type="button"
            onClick={() => navigate('/workspace')}
            className={`${modeCardBase} ${modeCardIdle}`}
          >
            <p className={`font-semibold text-sm mb-1 ${modeTitle}`}>Solo Write</p>
            <p className={`text-xs leading-relaxed hidden sm:block ${modeSub}`}>
              Full editor, no AI in the loop.
            </p>
          </button>

          {/* Collaborate */}
          <button
            type="button"
            onClick={() => setMode(mode === 'collaborate' ? null : 'collaborate')}
            className={`${modeCardBase} ${mode === 'collaborate' ? modeCardActive('emerald') : modeCardIdle}`}
          >
            <p className={`font-semibold text-sm mb-1 ${modeTitle}`}>
              Collaborate
              {mode === 'collaborate' && (
                <span className={`ml-2 text-[10px] font-normal ${modeActiveBadgeEmerald}`}>active</span>
              )}
            </p>
            <p className={`text-xs leading-relaxed hidden sm:block ${modeSub}`}>
              AI-guided continuations with pacing controls.
            </p>
          </button>

          {/* RP Reply */}
          <button
            type="button"
            onClick={() => setMode(mode === 'rp_reply' ? null : 'rp_reply')}
            className={`${modeCardBase} ${mode === 'rp_reply' ? modeCardActive('violet') : modeCardIdle}`}
          >
            <p className={`font-semibold text-sm mb-1 ${modeTitle}`}>
              RP Reply
              {mode === 'rp_reply' && (
                <span className={`ml-2 text-[10px] font-normal ${modeActiveBadgeViolet}`}>active</span>
              )}
            </p>
            <p className={`text-xs leading-relaxed hidden sm:block ${modeSub}`}>
              Generate your character's reply to a partner.
            </p>
          </button>
        </div>

        {/* ── Continue Writing (collapsible) ───────────────────────────── */}
        {loadingStories && (
          <div>
            <div className={`h-2 w-24 ${skeletonBg} rounded-full animate-pulse mb-4`} />
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className={`h-14 rounded-2xl ${skeletonCard} animate-pulse`} />
              ))}
            </div>
          </div>
        )}

        {!loadingStories && stories.length > 0 && (
          <div>
            {/* Section header */}
            <button
              type="button"
              onClick={() => setStoriesOpen(v => !v)}
              className="w-full flex items-center justify-between gap-2 mb-3 group"
            >
              <div className="flex items-center gap-2">
                <span className={`text-[11px] font-semibold uppercase tracking-widest ${sectionHdr}`}>
                  Continue Writing
                </span>
                <span className={`text-[11px] ${sectionHdr} opacity-60`}>
                  {stories.length} {stories.length === 1 ? 'story' : 'stories'}
                </span>
              </div>
              <span className={sectionChevron}>
                <ChevronDown open={storiesOpen} />
              </span>
            </button>

            {storiesOpen && (
              <div className="space-y-2">
                {recentStories.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => navigate(`/storylab/${s.id}`)}
                    className={storyCardCls}
                  >
                    <div
                      className="w-9 h-9 rounded-xl shrink-0 ring-1 ring-black/5"
                      style={{ backgroundColor: s.cover_color }}
                    />
                    <div className="min-w-0 flex-1">
                      <p className={storyTitle}>{storyLabel(s)}</p>
                      {s.genre && <p className={storyGenre}>{s.genre}</p>}
                    </div>
                    <span className={`${storyArrow} shrink-0 select-none text-lg leading-none`}>›</span>
                  </button>
                ))}
                {stories.length > RECENT_STORIES_LIMIT && (
                  <p className={`text-center text-xs pt-1 ${sectionHdr} opacity-60`}>
                    Showing {RECENT_STORIES_LIMIT} of {stories.length} stories
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Collaborate engine ────────────────────────────────────────── */}
      {mode === 'collaborate' && (
        <div className={`flex-1 flex flex-col border-t ${divider} min-h-0`}>
          <StoryLabEngine />
        </div>
      )}

      {/* ── RP Reply Generator ────────────────────────────────────────── */}
      {mode === 'rp_reply' && (
        <div className={`border-t ${divider}`}>
          <RPReplyGenerator theme={theme} />
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
