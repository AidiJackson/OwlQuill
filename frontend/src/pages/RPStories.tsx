import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type {
  RPStoryThread,
  Character,
  RPPartnerPOV,
  RPReplyIntensity,
} from '@/lib/types';

function ThreadCard({ thread, onClick }: { thread: RPStoryThread; onClick: () => void }) {
  const updated = new Date(thread.updated_at).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric',
  });
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full text-left p-5 rounded-2xl border transition-all group ${
        thread.status === 'archived'
          ? 'border-gray-800/30 bg-gray-900/20 opacity-60'
          : 'border-gray-800/50 bg-gray-900/40 hover:border-emerald-800/50 hover:bg-emerald-950/20'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-gray-100 text-sm truncate group-hover:text-emerald-300 transition-colors">
            {thread.title}
          </p>
          <p className="text-xs text-gray-500 mt-0.5">
            {thread.partner_label ? `with ${thread.partner_label}` : 'Partner unknown'}
            {thread.partner_pov !== 'unknown' && ` · ${thread.partner_pov} person`}
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-xs text-gray-600">{updated}</p>
          <p className="text-xs text-gray-600 mt-0.5">
            {thread.turn_count} turn{thread.turn_count !== 1 ? 's' : ''}
          </p>
        </div>
      </div>
      {thread.status === 'archived' && (
        <span className="mt-2 inline-block text-[10px] text-gray-600 bg-gray-800/50 px-1.5 py-0.5 rounded">
          archived
        </span>
      )}
    </button>
  );
}

export default function RPStories() {
  const navigate = useNavigate();

  const [threads, setThreads] = useState<RPStoryThread[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [showCreate, setShowCreate] = useState(false);

  // create form state
  const [starter, setStarter] = useState('');
  const [charId, setCharId] = useState<number | ''>('');
  const [partnerLabel, setPartnerLabel] = useState('');
  const [partnerPov, setPartnerPov] = useState<RPPartnerPOV>('unknown');
  const [title, setTitle] = useState('');
  const [intensity, setIntensity] = useState<RPReplyIntensity>('standard');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  useEffect(() => {
    Promise.all([
      apiClient.listRPStories(),
      apiClient.getCharacters(),
    ])
      .then(([t, chars]) => {
        setThreads(t);
        setCharacters(chars);
      })
      .catch(() => setError('Failed to load.'))
      .finally(() => setLoading(false));
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!starter.trim()) return;
    setCreating(true);
    setCreateError('');
    try {
      const thread = await apiClient.createRPStory({
        partner_starter: starter.trim(),
        selected_character_id: charId !== '' ? Number(charId) : null,
        partner_label: partnerLabel.trim() || null,
        partner_pov: partnerPov,
        title: title.trim() || null,
        intensity,
      });
      navigate(`/rp-stories/${thread.id}`);
    } catch (e: unknown) {
      setCreateError(e instanceof Error ? e.message : 'Failed to create thread.');
    } finally {
      setCreating(false);
    }
  }

  const activeThreads = threads.filter(t => t.status === 'active');
  const archivedThreads = threads.filter(t => t.status === 'archived');

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <div className="max-w-2xl mx-auto px-4 pt-10 pb-16">

        {/* Header */}
        <div className="mb-8 flex items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-gray-100">RP Stories</h1>
            <p className="mt-1.5 text-sm text-gray-500">
              Collaborative two-writer story threads. Your character. Their story.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowCreate(v => !v)}
            className={`shrink-0 px-4 py-2 rounded-xl text-sm font-medium border transition-all ${
              showCreate
                ? 'border-emerald-700 bg-emerald-950/50 text-emerald-300'
                : 'border-emerald-800/50 bg-emerald-950/30 text-emerald-400 hover:border-emerald-700'
            }`}
          >
            {showCreate ? 'Cancel' : '+ New Thread'}
          </button>
        </div>

        {/* Create form */}
        {showCreate && (
          <form
            onSubmit={handleCreate}
            className="mb-8 rounded-2xl border border-emerald-800/40 bg-emerald-950/20 p-6 space-y-5"
          >
            <h2 className="text-base font-semibold text-gray-100">Start an RP Story Thread</h2>

            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1.5">
                Partner's Opening Turn <span className="text-red-500">*</span>
              </label>
              <textarea
                value={starter}
                onChange={e => setStarter(e.target.value)}
                placeholder="Paste your writing partner's starter here…"
                rows={7}
                maxLength={20000}
                required
                className="w-full rounded-xl bg-black/50 border border-gray-700/60 text-gray-100 text-sm p-3 resize-y focus:outline-none focus:border-emerald-600/60 placeholder-gray-600 leading-relaxed"
              />
              <p className="text-[11px] text-gray-600 mt-1 text-right">
                {starter.length.toLocaleString()} / 20,000
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1.5">
                  Your Character
                </label>
                <select
                  value={charId}
                  onChange={e => setCharId(e.target.value === '' ? '' : Number(e.target.value))}
                  className="w-full bg-gray-900 border border-gray-700/60 rounded-xl text-sm text-gray-200 px-3 py-2 focus:outline-none focus:border-emerald-600/60"
                >
                  <option value="">— no character —</option>
                  {characters.map(c => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1.5">
                  Partner Label
                </label>
                <input
                  type="text"
                  value={partnerLabel}
                  onChange={e => setPartnerLabel(e.target.value)}
                  placeholder="e.g. Mira, Kael…"
                  maxLength={100}
                  className="w-full bg-gray-900 border border-gray-700/60 rounded-xl text-sm text-gray-200 px-3 py-2 focus:outline-none focus:border-emerald-600/60 placeholder-gray-600"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1.5">
                  Partner POV
                </label>
                <select
                  value={partnerPov}
                  onChange={e => setPartnerPov(e.target.value as RPPartnerPOV)}
                  className="w-full bg-gray-900 border border-gray-700/60 rounded-xl text-sm text-gray-200 px-3 py-2 focus:outline-none focus:border-emerald-600/60"
                >
                  <option value="unknown">Unknown</option>
                  <option value="first">First Person (I / me)</option>
                  <option value="third">Third Person (she / he / they)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1.5">
                  Content Level
                </label>
                <select
                  value={intensity}
                  onChange={e => setIntensity(e.target.value as RPReplyIntensity)}
                  className="w-full bg-gray-900 border border-gray-700/60 rounded-xl text-sm text-gray-200 px-3 py-2 focus:outline-none focus:border-emerald-600/60"
                >
                  <option value="standard">Standard</option>
                  <option value="mature">Mature</option>
                  <option value="explicit">Explicit</option>
                </select>
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1.5">
                Thread Title <span className="text-gray-600">(optional — auto-generated)</span>
              </label>
              <input
                type="text"
                value={title}
                onChange={e => setTitle(e.target.value)}
                placeholder="Leave blank to auto-title from the starter"
                maxLength={200}
                className="w-full bg-gray-900 border border-gray-700/60 rounded-xl text-sm text-gray-200 px-3 py-2 focus:outline-none focus:border-emerald-600/60 placeholder-gray-600"
              />
            </div>

            {createError && (
              <p className="text-red-400 text-sm">{createError}</p>
            )}

            <button
              type="submit"
              disabled={creating || !starter.trim()}
              className="w-full py-3 rounded-xl bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 text-white text-sm font-semibold transition-colors"
            >
              {creating ? 'Creating…' : 'Start RP Story Thread'}
            </button>
          </form>
        )}

        {/* Thread list */}
        {loading && (
          <p className="text-center text-gray-600 text-sm py-12">Loading threads…</p>
        )}
        {error && (
          <p className="text-center text-red-400 text-sm py-6">{error}</p>
        )}

        {!loading && !error && threads.length === 0 && !showCreate && (
          <div className="text-center py-16 space-y-3">
            <p className="text-gray-600 text-sm">No RP story threads yet.</p>
            <button
              type="button"
              onClick={() => setShowCreate(true)}
              className="text-emerald-500 hover:text-emerald-400 text-sm underline transition-colors"
            >
              Start your first thread
            </button>
          </div>
        )}

        {activeThreads.length > 0 && (
          <div className="space-y-3 mb-8">
            <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-3">
              Active
            </h2>
            {activeThreads.map(t => (
              <ThreadCard
                key={t.id}
                thread={t}
                onClick={() => navigate(`/rp-stories/${t.id}`)}
              />
            ))}
          </div>
        )}

        {archivedThreads.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-xs font-semibold text-gray-600 uppercase tracking-widest mb-3">
              Archived
            </h2>
            {archivedThreads.map(t => (
              <ThreadCard
                key={t.id}
                thread={t}
                onClick={() => navigate(`/rp-stories/${t.id}`)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
