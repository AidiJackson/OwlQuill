import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, Image, X, Check, Trash2, Flag } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { LibraryImage, UserImageRead, Character } from '@/lib/types';
import ErrorBoundary from '@/components/ErrorBoundary';
import SceneGeneratorPanel from '@/features/images/components/SceneGeneratorPanel';

type Tab = 'characters' | 'covers';

export default function Images() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<Tab>('characters');

  const [charImages, setCharImages] = useState<LibraryImage[]>([]);
  const [charLoading, setCharLoading] = useState(true);
  const [charError, setCharError] = useState('');

  const [coverImages, setCoverImages] = useState<UserImageRead[]>([]);
  const [coverLoading, setCoverLoading] = useState(true);
  const [coverError, setCoverError] = useState('');

  // The user's character for image generation
  const [myCharacter, setMyCharacter] = useState<Character | null>(null);

  // Weekly image allowance (B22)
  type QuotaStatus = { used: number; limit: number | null; remaining: number | null; unlimited: boolean };
  const [quota, setQuota] = useState<QuotaStatus | null>(null);

  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [lbVisible, setLbVisible] = useState(false);
  const [lightboxCoverId, setLightboxCoverId] = useState<number | null>(null);
  // Full image object when a character image is opened in the lightbox
  const [lightboxCharImage, setLightboxCharImage] = useState<LibraryImage | null>(null);
  const [applyingCover, setApplyingCover] = useState(false);
  const [applyCoverDone, setApplyCoverDone] = useState(false);
  const [applyCoverErr, setApplyCoverErr] = useState('');

  // Delete state
  const [deletingImage, setDeletingImage] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  // Report state
  const [reportStep, setReportStep] = useState<'idle' | 'form' | 'done'>('idle');
  const [reportReason, setReportReason] = useState('');
  const [reportSubmitting, setReportSubmitting] = useState(false);
  const [reportError, setReportError] = useState('');

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // Drives enter/exit transitions for the lightbox.
  useEffect(() => {
    if (!lightboxUrl) { setLbVisible(false); return; }
    const id = requestAnimationFrame(() => { if (mountedRef.current) setLbVisible(true); });
    return () => cancelAnimationFrame(id);
  }, [lightboxUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  const openLightbox = (url: string, coverId?: number, charImage?: LibraryImage) => {
    setLightboxUrl(url);
    setLightboxCoverId(coverId ?? null);
    setLightboxCharImage(charImage ?? null);
    setApplyCoverDone(false);
    setApplyCoverErr('');
    setDeleteError('');
    setReportStep('idle');
    setReportReason('');
    setReportError('');
  };

  const closeLightbox = () => {
    setLbVisible(false);
    setTimeout(() => {
      if (!mountedRef.current) return;
      setLightboxUrl(null);
      setLightboxCoverId(null);
      setLightboxCharImage(null);
      setApplyCoverDone(false);
      setApplyCoverErr('');
      setDeleteError('');
      setReportStep('idle');
      setReportReason('');
      setReportError('');
    }, 200);
  };

  const handleSetCover = async () => {
    if (!lightboxCoverId) return;
    setApplyingCover(true);
    setApplyCoverErr('');
    try {
      await apiClient.setMyProfileCover(lightboxCoverId);
      if (!mountedRef.current) return;
      setApplyCoverDone(true);
      setTimeout(() => { if (mountedRef.current) setApplyCoverDone(false); }, 2000);
    } catch (err) {
      if (!mountedRef.current) return;
      setApplyCoverErr(err instanceof Error ? err.message : 'Failed to set cover.');
    } finally {
      if (mountedRef.current) setApplyingCover(false);
    }
  };

  const handleDeleteImage = async () => {
    if (!lightboxCharImage) return;
    setDeletingImage(true);
    setDeleteError('');
    try {
      await apiClient.deleteCharacterImage(lightboxCharImage.character_id, lightboxCharImage.id);
      if (!mountedRef.current) return;
      setCharImages((prev) => prev.filter((img) => img.id !== lightboxCharImage.id));
      closeLightbox();
    } catch (err) {
      if (!mountedRef.current) return;
      setDeleteError(err instanceof Error ? err.message : 'Failed to delete image.');
    } finally {
      if (mountedRef.current) setDeletingImage(false);
    }
  };

  const handleSubmitReport = async () => {
    if (!lightboxCharImage || !reportReason.trim()) return;
    setReportSubmitting(true);
    setReportError('');
    try {
      await apiClient.submitReport('image', String(lightboxCharImage.id), reportReason.trim());
      if (!mountedRef.current) return;
      setReportStep('done');
    } catch (err) {
      if (!mountedRef.current) return;
      setReportError(err instanceof Error ? err.message : 'Failed to submit report.');
    } finally {
      if (mountedRef.current) setReportSubmitting(false);
    }
  };

  useEffect(() => {
    apiClient
      .listMyCharacterImages()
      .then((imgs) => setCharImages(imgs as unknown as LibraryImage[]))
      .catch((err) => setCharError(err instanceof Error ? err.message : 'Failed to load'))
      .finally(() => setCharLoading(false));

    apiClient
      .listMyUserImages('profile_cover')
      .then(setCoverImages)
      .catch((err) => setCoverError(err instanceof Error ? err.message : 'Failed to load'))
      .finally(() => setCoverLoading(false));

    // Fetch the user's character for the generator panel
    apiClient
      .getCharacters()
      .then((chars) => {
        const locked = chars.find((c) => c.visual_locked) || chars[0] || null;
        if (mountedRef.current) setMyCharacter(locked ?? null);
      })
      .catch(() => {});

    // Fetch weekly image allowance (B22)
    apiClient
      .getImageQuota()
      .then((q) => { if (mountedRef.current) setQuota(q); })
      .catch(() => {});
  }, []);

  const tabs: { id: Tab; label: string; count: number }[] = [
    { id: 'characters', label: 'Characters', count: charImages.length },
    { id: 'covers', label: 'Covers', count: coverImages.length },
  ];

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <div className="border-b border-gray-800 bg-gray-900/50">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link to="/" className="text-gray-400 hover:text-gray-200 transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <span className="text-sm font-medium text-gray-300">Image Library</span>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-6 space-y-6">
        {/* Tabs */}
        <div className="flex items-center gap-1 border-b border-gray-800">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
                activeTab === tab.id
                  ? 'border-emerald-500 text-emerald-300'
                  : 'border-transparent text-gray-500 hover:text-gray-300'
              }`}
            >
              {tab.label}
              {!charLoading && !coverLoading && (
                <span className="ml-1.5 text-xs text-gray-600">{tab.count}</span>
              )}
            </button>
          ))}
        </div>

        {/* Characters tab */}
        {activeTab === 'characters' && (
          <>
            {/* Image generator */}
            {myCharacter && (
              <SceneGeneratorPanel
                characterId={myCharacter.id}
                isCharacterLocked={myCharacter.visual_locked ?? false}
                onGenerated={(image) => {
                  setCharImages((prev) => [image as unknown as LibraryImage, ...prev]);
                  setQuota((q) =>
                    q && !q.unlimited && q.remaining !== null
                      ? { ...q, used: q.used + 1, remaining: Math.max(0, q.remaining - 1) }
                      : q
                  );
                }}
              />
            )}

            {/* Weekly allowance (B22) */}
            {quota && !quota.unlimited && (
              <p className={`text-xs ${quota.remaining === 0 ? 'text-amber-400' : 'text-gray-500'}`}>
                {quota.remaining === 0
                  ? "You've used all your images for this week."
                  : `${quota.remaining} of ${quota.limit} images remaining this week`}
              </p>
            )}

            {charError && (
              <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2">
                {charError}
              </p>
            )}
            {charLoading ? (
              <div className="flex items-center justify-center py-16 text-gray-400">Loading...</div>
            ) : charImages.length === 0 ? (
              <EmptyState
                message={
                  myCharacter
                    ? 'No images yet. Use the generator above to create your first image.'
                    : 'Create a character to generate images.'
                }
                primaryAction={
                  !myCharacter
                    ? { label: 'Create character', onClick: () => navigate('/characters/new') }
                    : undefined
                }
                secondaryAction={
                  !myCharacter
                    ? { label: 'Go to Characters', onClick: () => navigate('/characters') }
                    : undefined
                }
              />
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {charImages.map((img) => (
                  <button
                    key={img.id}
                    className="rounded-lg border border-gray-800 overflow-hidden bg-gray-900 hover:border-gray-600 transition-colors cursor-pointer text-left"
                    onClick={() => openLightbox(img.url, undefined, img)}
                  >
                    <img
                      src={img.url}
                      alt={img.prompt_summary || img.kind}
                      className="w-full aspect-[2/3] object-cover"
                    />
                    <div className="px-2 py-1.5">
                      <p className="text-xs text-gray-400 truncate">
                        {img.kind.replace(/_/g, ' ')}
                      </p>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        {/* Covers tab */}
        {activeTab === 'covers' && (
          <>
            {coverError && (
              <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2">
                {coverError}
              </p>
            )}
            {coverLoading ? (
              <div className="flex items-center justify-center py-16 text-gray-400">Loading...</div>
            ) : coverImages.length === 0 ? (
              <EmptyState message="No cover images yet. Generate a profile cover from your profile page." />
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {coverImages.map((img) => (
                  <button
                    key={img.id}
                    className="rounded-lg border border-gray-800 overflow-hidden bg-gray-900 hover:border-gray-600 transition-colors cursor-pointer text-left"
                    onClick={() => openLightbox(img.url, img.id)}
                  >
                    <img
                      src={img.url}
                      alt={img.prompt_summary || 'Profile cover'}
                      className="w-full aspect-[2048/720] object-cover"
                    />
                    <div className="px-2 py-1.5">
                      <p className="text-xs text-gray-400 truncate">
                        {img.prompt_summary?.replace('preset:', '') || 'Cover'}
                      </p>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Lightbox */}
      <ErrorBoundary>
      {lightboxUrl && (
        <div
          className={`fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm transition-opacity duration-200 ${lbVisible ? 'opacity-100' : 'opacity-0'}`}
          onClick={closeLightbox}
        >
          <div
            className={`relative max-w-3xl w-full mx-4 transition-all duration-200 ease-out ${lbVisible ? 'opacity-100 scale-100' : 'opacity-0 scale-95'}`}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="absolute top-3 right-3 p-1.5 rounded-full bg-black/60 text-white hover:bg-black/80 z-10"
              onClick={closeLightbox}
            >
              <X className="w-4 h-4" />
            </button>
            <img
              src={lightboxUrl}
              alt="Full size"
              className="w-full rounded-lg"
            />

            {/* Cover image actions */}
            {lightboxCoverId !== null && (
              <div className="flex items-center justify-between mt-2">
                <div>
                  {applyCoverErr && (
                    <p className="text-xs text-red-400">{applyCoverErr}</p>
                  )}
                </div>
                <button
                  className="text-xs px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white transition-colors disabled:opacity-50 flex items-center gap-1.5"
                  disabled={applyingCover}
                  onClick={handleSetCover}
                >
                  {applyCoverDone ? (
                    <><Check className="w-3 h-3" />Cover set</>
                  ) : applyingCover ? (
                    'Setting...'
                  ) : (
                    'Set as profile cover'
                  )}
                </button>
              </div>
            )}

            {/* Character image actions: delete + report */}
            {lightboxCharImage && (
              <div className="mt-2 space-y-2">
                {deleteError && (
                  <p className="text-xs text-red-400">{deleteError}</p>
                )}
                <div className="flex items-center justify-between">
                  <button
                    className="text-xs text-gray-400 hover:text-gray-200 transition-colors flex items-center gap-1"
                    onClick={() => setReportStep(reportStep === 'form' ? 'idle' : 'form')}
                  >
                    <Flag className="w-3 h-3" />
                    Report issue
                  </button>
                  <button
                    className="text-xs px-3 py-1.5 rounded bg-red-900/60 hover:bg-red-800 text-red-300 transition-colors disabled:opacity-50 flex items-center gap-1.5"
                    disabled={deletingImage}
                    onClick={handleDeleteImage}
                  >
                    <Trash2 className="w-3 h-3" />
                    {deletingImage ? 'Deleting…' : 'Delete'}
                  </button>
                </div>

                {reportStep === 'form' && (
                  <div className="border border-gray-700 rounded-lg p-3 space-y-2 bg-gray-900">
                    <p className="text-xs font-medium text-gray-300">Report this image</p>
                    <textarea
                      className="textarea w-full text-sm"
                      rows={2}
                      maxLength={200}
                      placeholder="Describe the issue…"
                      value={reportReason}
                      onChange={(e) => setReportReason(e.target.value)}
                    />
                    {reportError && <p className="text-xs text-red-400">{reportError}</p>}
                    <div className="flex gap-2 justify-end">
                      <button
                        className="text-xs text-gray-400 hover:text-gray-200 transition-colors"
                        onClick={() => setReportStep('idle')}
                      >
                        Cancel
                      </button>
                      <button
                        className="text-xs px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-white transition-colors disabled:opacity-50"
                        disabled={reportSubmitting || !reportReason.trim()}
                        onClick={handleSubmitReport}
                      >
                        {reportSubmitting ? 'Submitting…' : 'Submit'}
                      </button>
                    </div>
                  </div>
                )}

                {reportStep === 'done' && (
                  <p className="text-xs text-emerald-400">Report submitted. Thank you.</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}
      </ErrorBoundary>
    </div>
  );
}

interface EmptyStateProps {
  message: string;
  primaryAction?: { label: string; onClick: () => void };
  secondaryAction?: { label: string; onClick: () => void };
}

function EmptyState({ message, primaryAction, secondaryAction }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center text-center py-16 space-y-4">
      <div className="w-14 h-14 rounded-full bg-emerald-900/40 border border-emerald-600/20 flex items-center justify-center">
        <Image className="w-7 h-7 text-emerald-400" />
      </div>
      <h2 className="text-lg font-semibold text-gray-200">No images yet</h2>
      <p className="text-sm text-gray-400 max-w-sm">{message}</p>
      {(primaryAction || secondaryAction) && (
        <div className="flex items-center gap-2 pt-1">
          {primaryAction && (
            <button onClick={primaryAction.onClick} className="btn btn-primary text-sm">
              {primaryAction.label}
            </button>
          )}
          {secondaryAction && (
            <button onClick={secondaryAction.onClick} className="btn btn-secondary text-sm">
              {secondaryAction.label}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
