import { useState, useEffect } from 'react';
import { useParams, useSearchParams, useNavigate, Link } from 'react-router-dom';
import { ArrowLeft, Globe, Users, Lock, Feather, ImageIcon, RefreshCw, MessageSquare, UserPlus, UserCheck, Trash2 } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { Character, User } from '@/lib/types';
import { generateMomentImage, resolveImageUrl } from '@/features/characterCreation/shared/api';
import type { CharacterImageRead } from '@/features/characterCreation/shared/types';

const VISIBILITY_ICONS = {
  public: Globe,
  friends: Users,
  private: Lock,
} as const;

export default function CharacterDetail() {
  const { id } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const [character, setCharacter] = useState<Character | null>(null);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const justCreated = searchParams.get('created') === '1';

  const [following, setFollowing] = useState(false);

  const [momentImage, setMomentImage] = useState<CharacterImageRead | null>(null);
  const [momentLoading, setMomentLoading] = useState(false);
  const [momentError, setMomentError] = useState('');

  // Delete modal state
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleteStep, setDeleteStep] = useState<1 | 2>(1);
  const [deleteConfirmed, setDeleteConfirmed] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  const handleDeleteCharacter = async () => {
    if (!id) return;
    setDeleting(true);
    setDeleteError('');
    try {
      await apiClient.deleteCharacter(Number(id));
      navigate('/characters');
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'Failed to delete character.');
      setDeleting(false);
    }
  };

  const openDeleteModal = () => {
    setShowDeleteModal(true);
    setDeleteStep(1);
    setDeleteConfirmed(false);
    setDeleteError('');
  };

  const closeDeleteModal = () => {
    setShowDeleteModal(false);
    setDeleteStep(1);
    setDeleteConfirmed(false);
    setDeleteError('');
  };

  const handleGenerateMoment = async () => {
    if (!id) return;
    setMomentLoading(true);
    setMomentError('');
    try {
      const img = await generateMomentImage(Number(id), {});
      setMomentImage(img);
    } catch (err) {
      setMomentError(err instanceof Error ? err.message : 'Could not generate image.');
    } finally {
      setMomentLoading(false);
    }
  };

  useEffect(() => {
    if (!id) return;
    Promise.all([
      apiClient.getCharacter(Number(id)),
      apiClient.getMe().catch(() => null),
    ])
      .then(([char, user]) => {
        setCharacter(char);
        setCurrentUser(user);
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Character not found'))
      .finally(() => setLoading(false));
  }, [id]);

  const dismissBanner = () => {
    searchParams.delete('created');
    setSearchParams(searchParams, { replace: true });
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-400">
        Loading…
      </div>
    );
  }

  if (error || !character) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <p className="text-gray-400">{error || 'Character not found.'}</p>
        <button className="btn btn-secondary" onClick={() => navigate('/characters')}>
          Back to Characters
        </button>
      </div>
    );
  }

  const VisIcon = VISIBILITY_ICONS[character.visibility] || Globe;

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <div className="border-b border-gray-800 bg-gray-900/50">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link
            to="/characters"
            className="text-gray-400 hover:text-gray-200 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <span className="text-sm font-medium text-gray-300 truncate">
            {character.name}
          </span>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-6 space-y-6">
        {/* Arrival banner */}
        {justCreated && (
          <div className="flex items-center justify-between gap-3 bg-owl-600/10 border border-owl-600/20 rounded-lg px-4 py-3">
            <div className="flex items-center gap-2">
              <Feather className="w-4 h-4 text-owl-400 flex-shrink-0" />
              <span className="text-sm text-owl-300">
                Your character now lives on OwlQuill.
              </span>
            </div>
            <button
              onClick={dismissBanner}
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors flex-shrink-0"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Header */}
        <div className="flex gap-5 items-start">
          {character.avatar_url ? (
            <img
              src={character.avatar_url}
              alt={character.name}
              className="w-28 h-28 rounded-lg object-cover border border-gray-800 flex-shrink-0"
            />
          ) : (
            <div className="w-28 h-28 rounded-lg bg-gray-800 border border-gray-700 flex items-center justify-center flex-shrink-0">
              <Feather className="w-8 h-8 text-gray-600" />
            </div>
          )}
          <div className="min-w-0 space-y-1.5">
            <h1 className="text-2xl font-bold text-gray-100 truncate">{character.name}</h1>
            {(character.species || character.role || character.era) && (
              <p className="text-sm text-gray-400">
                {[character.species, character.role, character.era].filter(Boolean).join(' · ')}
              </p>
            )}
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <VisIcon className="w-3.5 h-3.5" />
              <span className="capitalize">{character.visibility}</span>
            </div>
            <div className="flex items-center gap-2 mt-2">
              {currentUser && character.owner_id === currentUser.id ? (
                <button
                  className="btn btn-secondary text-sm flex items-center gap-2 opacity-50 cursor-not-allowed"
                  disabled
                >
                  <MessageSquare className="w-3.5 h-3.5" />
                  Message
                </button>
              ) : (
                <button
                  className="btn btn-secondary text-sm flex items-center gap-2"
                  onClick={() => navigate(`/messages/new?characterId=${id}`)}
                >
                  <MessageSquare className="w-3.5 h-3.5" />
                  Message
                </button>
              )}
              <button
                className={`text-sm flex items-center gap-2 ${
                  following
                    ? 'btn btn-secondary'
                    : 'btn btn-primary'
                }`}
                onClick={() => setFollowing((prev) => !prev)}
              >
                {following ? (
                  <><UserCheck className="w-3.5 h-3.5" />Following</>
                ) : (
                  <><UserPlus className="w-3.5 h-3.5" />Follow</>
                )}
              </button>
            </div>
            {following && (
              <p className="text-xs text-gray-500 mt-1">Follow system coming next.</p>
            )}
            {currentUser && character.owner_id === currentUser.id && (
              <p className="text-xs text-gray-500 mt-1">You can't message your own character.</p>
            )}
            {currentUser && character.owner_id === currentUser.id && (
              <button
                className="text-xs text-red-500 hover:text-red-400 transition-colors mt-2 flex items-center gap-1"
                onClick={openDeleteModal}
              >
                <Trash2 className="w-3 h-3" />
                Reset Character Identity
              </button>
            )}
          </div>
        </div>

        {/* Bio */}
        {character.short_bio && (
          <p className="text-gray-300">{character.short_bio}</p>
        )}
        {character.long_bio && (
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
            <p className="text-sm text-gray-300 whitespace-pre-wrap">{character.long_bio}</p>
          </div>
        )}

        {/* Tags */}
        {character.tags && (
          <div className="flex flex-wrap gap-2">
            {character.tags.split(',').map((tag, i) => (
              <span
                key={i}
                className="px-2 py-1 bg-owl-900 text-owl-300 text-xs rounded"
              >
                {tag.trim()}
              </span>
            ))}
          </div>
        )}

        {/* Moment generation (post-lock) */}
        {character.visual_locked && (
          <div className="border-t border-gray-800 pt-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium text-gray-300">New moment</h2>
              <button
                className="btn btn-primary text-sm flex items-center gap-2"
                onClick={handleGenerateMoment}
                disabled={momentLoading}
              >
                {momentLoading ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    Generating…
                  </>
                ) : (
                  <>
                    <ImageIcon className="w-3.5 h-3.5" />
                    Generate new moment
                  </>
                )}
              </button>
            </div>

            {momentError && (
              <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2">
                {momentError}
              </p>
            )}

            {momentImage && (
              <div className="rounded-lg overflow-hidden border border-gray-800 bg-gray-900 inline-block">
                <img
                  src={resolveImageUrl(momentImage.url)}
                  alt="Latest moment"
                  className="max-w-xs w-full"
                />
                <div className="px-3 py-2">
                  <span className="text-xs text-gray-400">Latest moment</span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Delete character modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-6 max-w-md w-full mx-4 space-y-4">
            {deleteStep === 1 ? (
              <>
                <h3 className="text-lg font-semibold text-red-400">Reset Character Identity</h3>
                <div className="text-sm text-gray-300 space-y-2">
                  <p>This will <strong>permanently delete</strong> your character <strong>{character.name}</strong> and all associated data:</p>
                  <ul className="list-disc list-inside text-gray-400 space-y-1">
                    <li>Character profile, bio, and DNA</li>
                    <li>All generated images (identity pack, moments)</li>
                    <li>All conversations and messages as this character</li>
                    <li>Character references on posts will be cleared</li>
                  </ul>
                  <p className="text-amber-400">After deletion, you must wait <strong>24 hours</strong> before creating a new character.</p>
                </div>
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={deleteConfirmed}
                    onChange={(e) => setDeleteConfirmed(e.target.checked)}
                    className="mt-1 accent-red-500"
                  />
                  <span className="text-sm text-gray-300">I understand this action is permanent and cannot be undone.</span>
                </label>
                <div className="flex gap-3 pt-2">
                  <button
                    className="btn btn-secondary text-sm flex-1"
                    onClick={closeDeleteModal}
                  >
                    Cancel
                  </button>
                  <button
                    className="bg-red-600 hover:bg-red-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm px-4 py-2 rounded transition-colors flex-1"
                    disabled={!deleteConfirmed}
                    onClick={() => setDeleteStep(2)}
                  >
                    Continue
                  </button>
                </div>
              </>
            ) : (
              <>
                <h3 className="text-lg font-semibold text-red-400">Final Confirmation</h3>
                <p className="text-sm text-gray-300">
                  Are you absolutely sure you want to permanently delete <strong>{character.name}</strong>?
                </p>
                {deleteError && (
                  <p className="text-sm text-red-400 bg-red-400/10 rounded-lg px-3 py-2">{deleteError}</p>
                )}
                <div className="flex gap-3 pt-2">
                  <button
                    className="btn btn-secondary text-sm flex-1"
                    onClick={closeDeleteModal}
                    disabled={deleting}
                  >
                    Cancel
                  </button>
                  <button
                    className="bg-red-600 hover:bg-red-500 disabled:opacity-40 text-white text-sm px-4 py-2 rounded transition-colors flex-1"
                    onClick={handleDeleteCharacter}
                    disabled={deleting}
                  >
                    {deleting ? 'Deleting...' : 'Delete Character Permanently'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
