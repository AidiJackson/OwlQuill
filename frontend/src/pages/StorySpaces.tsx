import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { StorySpaceListItem } from '@/lib/types';

// ── Create modal ──────────────────────────────────────────────────────────────

interface CreateModalProps {
  onCreated: (space: StorySpaceListItem) => void;
  onCancel: () => void;
}

function CreateSpaceModal({ onCreated, onCancel }: CreateModalProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  function handleBackdropKey(e: React.KeyboardEvent) {
    if (e.key === 'Escape') onCancel();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setSubmitting(true);
    setError('');
    try {
      const space = await apiClient.createStorySpace({
        name: trimmed,
        description: description.trim() || undefined,
      });
      // API returns SpaceRead; adapt to list item shape for immediate use
      onCreated({
        id: space.id,
        owner_id: space.owner_id,
        name: space.name,
        slug: space.slug,
        description: space.description,
        cover_url: space.cover_url,
        your_role: space.your_role,
        member_count: space.member_count,
        created_at: space.created_at,
        updated_at: space.updated_at,
      });
    } catch (err) {
      setError((err as Error).message || 'Could not create space. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onKeyDown={handleBackdropKey}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onCancel} />

      {/* Panel */}
      <div className="relative z-10 w-full max-w-md bg-gray-950 border border-gray-800 rounded-2xl shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-5 pb-4 border-b border-gray-800/60">
          <div>
            <h2 className="text-base font-semibold text-gray-100">New Story Space</h2>
            <p className="text-xs text-gray-500 mt-0.5">Private — invite only</p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="text-gray-600 hover:text-gray-400 transition-colors p-1 rounded-lg hover:bg-gray-800"
            aria-label="Close"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit}>
          <div className="px-6 py-5 space-y-4">
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1.5">
                Name <span className="text-red-500">*</span>
              </label>
              <input
                ref={nameRef}
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Ashenveil Chronicles"
                maxLength={100}
                required
                className="w-full rounded-xl bg-gray-900/60 border border-gray-800/70 px-3 py-2.5 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-emerald-700/60 transition"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1.5">
                Description <span className="text-gray-600">(optional)</span>
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What's this space for?"
                rows={3}
                className="w-full resize-none rounded-xl bg-gray-900/60 border border-gray-800/70 px-3 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-emerald-700/60 transition leading-relaxed"
              />
            </div>

            {error && (
              <p className="text-xs text-red-400 bg-red-900/20 border border-red-700/40 rounded-lg px-3 py-2">
                {error}
              </p>
            )}
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-gray-800/60 flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={onCancel}
              className="px-4 py-2 text-sm rounded-xl border border-gray-700/60 bg-gray-900/40 hover:bg-gray-800/50 hover:border-gray-600 text-gray-400 hover:text-gray-300 transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !name.trim()}
              className="px-5 py-2 text-sm rounded-xl bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white font-semibold transition disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {submitting ? 'Creating…' : 'Create Space'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Space card ────────────────────────────────────────────────────────────────

function SpaceCard({ space, onOpen }: { space: StorySpaceListItem; onOpen: () => void }) {
  const isOwner = space.your_role === 'owner';

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 flex flex-col gap-3 hover:border-gray-700 transition-colors">
      {/* Top row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <h3 className="text-base font-semibold text-gray-100 truncate">{space.name}</h3>
          {space.description && (
            <p className="text-sm text-gray-400 mt-1 line-clamp-2">{space.description}</p>
          )}
        </div>
        {/* Role badge */}
        <span
          className={`flex-shrink-0 text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full border ${
            isOwner
              ? 'bg-emerald-900/40 border-emerald-700/60 text-emerald-400'
              : 'bg-gray-800 border-gray-700 text-gray-500'
          }`}
        >
          {isOwner ? 'Owner' : 'Member'}
        </span>
      </div>

      {/* Meta row */}
      <div className="flex items-center gap-3 text-xs text-gray-600">
        <span className="flex items-center gap-1">
          {/* Lock icon */}
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
          </svg>
          Private · Invite only
        </span>
        <span className="text-gray-700">·</span>
        <span className="flex items-center gap-1">
          {/* Members icon */}
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          {space.member_count} {space.member_count === 1 ? 'member' : 'members'}
        </span>
      </div>

      {/* Action row */}
      <div className="pt-1">
        <button
          onClick={onOpen}
          className="px-4 py-1.5 text-sm rounded-lg bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white font-medium transition-colors"
        >
          Open
        </button>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function StorySpaces() {
  const navigate = useNavigate();
  const [spaces, setSpaces] = useState<StorySpaceListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    void loadSpaces();
  }, []);

  async function loadSpaces() {
    setLoading(true);
    setError('');
    try {
      const data = await apiClient.getStorySpaces();
      setSpaces(data);
    } catch (err) {
      setError((err as Error).message || 'Could not load spaces.');
    } finally {
      setLoading(false);
    }
  }

  function handleCreated(space: StorySpaceListItem) {
    setShowCreate(false);
    setSpaces((prev) => [space, ...prev]);
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-10">
      {/* Page header */}
      <div className="mb-8">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-100">Story Spaces</h1>
            <p className="text-sm text-gray-500 mt-1">
              Private places to write, plan, and publish with chosen partners.
            </p>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="flex-shrink-0 flex items-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white text-sm font-semibold transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            Create Story Space
          </button>
        </div>
      </div>

      {/* Loading skeleton */}
      {loading && (
        <div className="grid gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-gray-900 border border-gray-800 rounded-xl p-5 animate-pulse">
              <div className="h-4 bg-gray-800 rounded w-48 mb-3" />
              <div className="h-3 bg-gray-800 rounded w-full mb-2" />
              <div className="h-3 bg-gray-800 rounded w-2/3" />
            </div>
          ))}
        </div>
      )}

      {/* Error */}
      {!loading && error && (
        <div className="rounded-xl bg-red-900/20 border border-red-700/40 px-4 py-3 text-sm text-red-400">
          {error}
          <button
            onClick={() => void loadSpaces()}
            className="ml-3 underline hover:no-underline transition-all"
          >
            Retry
          </button>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && spaces.length === 0 && (
        <div className="text-center py-20 space-y-4">
          <div className="w-14 h-14 rounded-2xl bg-gray-900 border border-gray-800 flex items-center justify-center mx-auto">
            <svg className="w-6 h-6 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
            </svg>
          </div>
          <div>
            <p className="text-gray-400 font-medium">No spaces yet</p>
            <p className="text-sm text-gray-600 mt-1">Create one or wait for an invite from a collaborator.</p>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-semibold transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            Create Story Space
          </button>
        </div>
      )}

      {/* Space list */}
      {!loading && !error && spaces.length > 0 && (
        <div className="grid gap-4">
          {spaces.map((space) => (
            <SpaceCard
              key={space.id}
              space={space}
              onOpen={() => navigate(`/spaces/${space.id}`)}
            />
          ))}
        </div>
      )}

      {/* Create modal */}
      {showCreate && (
        <CreateSpaceModal
          onCreated={handleCreated}
          onCancel={() => setShowCreate(false)}
        />
      )}
    </div>
  );
}
