import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Image, X, Check, Trash2, Flag } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { LibraryImage, Character } from '@/lib/types';
import ErrorBoundary from '@/components/ErrorBoundary';
import SceneGeneratorPanel from '@/features/images/components/SceneGeneratorPanel';

type Tab = 'characters' | 'covers';

export default function Images() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [activeTab, setActiveTab] = useState<Tab>(
    searchParams.get('tab') === 'covers' ? 'covers' : 'characters'
  );

  const [charImages, setCharImages] = useState<LibraryImage[]>([]);
  const [charLoading, setCharLoading] = useState(true);
  const [charError, setCharError] = useState('');

  // Character cover assignment state (Covers tab lightbox)
  const [lightboxCoverCharImage, setLightboxCoverCharImage] = useState<LibraryImage | null>(null);
  const [assignCharId, setAssignCharId] = useState<number | null>(null);
  const [assigningCover, setAssigningCover] = useState(false);
  const [assignCoverDone, setAssignCoverDone] = useState(false);
  const [assignCoverErr, setAssignCoverErr] = useState('');

  // The user's characters for the generator selector
  const [myCharacters, setMyCharacters] = useState<Character[]>([]);

  // Weekly image allowance (B22/B23)
  type QuotaStatus = {
    used: number;
    limit: number | null;
    remaining: number | null;
    unlimited: boolean;
    reset_at?: string | null;
  };
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

  const openLightbox = (url: string, coverId?: number, charImage?: LibraryImage, coverCharImage?: LibraryImage) => {
    setLightboxUrl(url);
    setLightboxCoverId(coverId ?? null);
    setLightboxCharImage(charImage ?? null);
    setLightboxCoverCharImage(coverCharImage ?? null);
    setAssignCharId(myCharacters.length === 1 ? myCharacters[0].id : null);
    setApplyCoverDone(false);
    setApplyCoverErr('');
    setAssignCoverDone(false);
    setAssignCoverErr('');
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
      setLightboxCoverCharImage(null);
      setAssignCharId(null);
      setApplyCoverDone(false);
      setApplyCoverErr('');
      setAssignCoverDone(false);
      setAssignCoverErr('');
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

  const handleAssignCover = async () => {
    if (!lightboxCoverCharImage || assignCharId === null) return;
    setAssigningCover(true);
    setAssignCoverErr('');
    try {
      await apiClient.setCharacterCover(assignCharId, 'character', lightboxCoverCharImage.id);
      if (!mountedRef.current) return;
      setAssignCoverDone(true);
      setTimeout(() => { if (mountedRef.current) setAssignCoverDone(false); }, 2000);
    } catch (err) {
      if (!mountedRef.current) return;
      setAssignCoverErr(err instanceof Error ? err.message : 'Failed to set cover.');
    } finally {
      if (mountedRef.current) setAssigningCover(false);
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

    // Fetch all user characters for the generator selector
    apiClient
      .getCharacters()
      .then((chars) => { if (mountedRef.current) setMyCharacters(chars); })
      .catch(() => {});

    // Fetch weekly image allowance (B22)
    apiClient
      .getImageQuota()
      .then((q) => { if (mountedRef.current) setQuota(q); })
      .catch(() => {});
  }, []);

  // Only show generated images in the gallery — anchor/face-ref images are internal and
  // cannot be deleted, so displaying them confuses users and breaks delete/report actions.
  const generatedCharImages = charImages.filter((img) => img.kind === 'generated');
  // Cover images (banner-style, kind=cover) displayed in the Covers tab
  const coverCharImages = charImages.filter((img) => img.kind === 'cover');

  const tabs: { id: Tab; label: string; count: number }[] = [
    { id: 'characters', label: 'Characters', count: generatedCharImages.length },
    { id: 'covers', label: 'Covers', count: coverCharImages.length },
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
              {!charLoading && (
                <span className="ml-1.5 text-xs text-gray-600">{tab.count}</span>
              )}
            </button>
          ))}
        </div>

        {/* Characters tab */}
        {activeTab === 'characters' && (
          <>
            {/* Image generator */}
            {myCharacters.length > 0 && (
              <SceneGeneratorPanel
                characters={myCharacters}
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

            {/* Weekly allowance (B23) */}
            {quota && !quota.unlimited && (
              quota.remaining === 0 ? (
                <div className="space-y-0.5">
                  <p className="text-xs text-amber-400">
                    You've used all {quota.limit} images for this week.
                  </p>
                  <p className="text-xs text-gray-500">
                    {quota.reset_at
                      ? `Your allowance resets ${formatResetTime(quota.reset_at)}.`
                      : 'Your allowance resets weekly.'}
                  </p>
                </div>
              ) : (
                <p className="text-xs text-gray-500">
                  {quota.remaining} of {quota.limit} image{quota.limit !== 1 ? 's' : ''} remaining this week
                </p>
              )
            )}

            {charError && (
              <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2">
                {charError}
              </p>
            )}
            {charLoading ? (
              <div className="flex items-center justify-center py-16 text-gray-400">Loading...</div>
            ) : generatedCharImages.length === 0 ? (
              <EmptyState
                message={
                  myCharacters.length > 0
                    ? 'No images yet. Use the generator above to create your first image.'
                    : 'Create a character to generate images.'
                }
                primaryAction={
                  myCharacters.length === 0
                    ? { label: 'Create character', onClick: () => navigate('/characters/new') }
                    : undefined
                }
                secondaryAction={
                  myCharacters.length === 0
                    ? { label: 'Go to Characters', onClick: () => navigate('/characters') }
                    : undefined
                }
              />
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {generatedCharImages.map((img) => (
                  <button
                    key={img.id}
                    className="rounded-lg border border-gray-800 overflow-hidden bg-gray-900 hover:border-gray-600 transition-colors cursor-pointer text-left"
                    onClick={() => openLightbox(img.url, undefined, img)}
                    title="Click to view, delete, or report"
                  >
                    <img
                      src={img.url}
                      alt={img.prompt_summary || 'Generated image'}
                      className="w-full aspect-[2/3] object-cover"
                    />
                    {img.prompt_summary && (
                      <div className="px-2 py-1.5">
                        <p className="text-xs text-gray-400 truncate">{img.prompt_summary}</p>
                      </div>
                    )}
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        {/* Covers tab */}
        {activeTab === 'covers' && (
          <>
            {/* Cover generator */}
            {myCharacters.length > 0 && (
              <SceneGeneratorPanel
                characters={myCharacters}
                isCover
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

            {/* Weekly allowance */}
            {quota && !quota.unlimited && (
              quota.remaining === 0 ? (
                <div className="space-y-0.5">
                  <p className="text-xs text-amber-400">
                    You've used all {quota.limit} images for this week.
                  </p>
                  <p className="text-xs text-gray-500">
                    {quota.reset_at
                      ? `Your allowance resets ${formatResetTime(quota.reset_at)}.`
                      : 'Your allowance resets weekly.'}
                  </p>
                </div>
              ) : (
                <p className="text-xs text-gray-500">
                  {quota.remaining} of {quota.limit} image{quota.limit !== 1 ? 's' : ''} remaining this week
                </p>
              )
            )}

            {charError && (
              <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2">
                {charError}
              </p>
            )}
            {charLoading ? (
              <div className="flex items-center justify-center py-16 text-gray-400">Loading...</div>
            ) : coverCharImages.length === 0 ? (
              <EmptyState
                message={
                  myCharacters.length > 0
                    ? 'No cover images yet. Use the generator above to create your first banner.'
                    : 'Create a character to generate cover images.'
                }
                primaryAction={
                  myCharacters.length === 0
                    ? { label: 'Create character', onClick: () => navigate('/characters/new') }
                    : undefined
                }
              />
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {coverCharImages.map((img) => (
                  <button
                    key={img.id}
                    className="rounded-lg border border-gray-800 overflow-hidden bg-gray-900 hover:border-gray-600 transition-colors cursor-pointer text-left"
                    onClick={() => openLightbox(img.url, undefined, undefined, img)}
                  >
                    <img
                      src={img.url}
                      alt={img.prompt_summary || 'Cover image'}
                      className="w-full aspect-[2048/720] object-cover"
                    />
                    {img.prompt_summary && (
                      <div className="px-2 py-1.5">
                        <p className="text-xs text-gray-400 truncate">{img.prompt_summary}</p>
                      </div>
                    )}
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
          className={`fixed inset-0 z-50 overflow-y-auto bg-black/80 backdrop-blur-sm transition-opacity duration-200 ${lbVisible ? 'opacity-100' : 'opacity-0'}`}
          onClick={closeLightbox}
        >
          <div className="flex min-h-full items-center justify-center p-4">
          <div
            className={`relative max-w-3xl w-full transition-all duration-200 ease-out ${lbVisible ? 'opacity-100 scale-100' : 'opacity-0 scale-95'}`}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="absolute top-3 right-3 p-1.5 rounded-full bg-black/60 text-white hover:bg-black/80 z-10"
              onClick={closeLightbox}
            >
              <X className="w-4 h-4" />
            </button>
            {lightboxCoverCharImage ? (
              <div className="relative w-full rounded-lg overflow-hidden aspect-[2048/720]">
                <img
                  src={lightboxUrl}
                  alt="Banner preview"
                  className="w-full h-full object-cover"
                />
                <span className="absolute bottom-2 left-2 text-[10px] text-white/60 bg-black/50 px-1.5 py-0.5 rounded">
                  Banner crop preview
                </span>
              </div>
            ) : (
              <img
                src={lightboxUrl}
                alt="Full size"
                className="w-full rounded-lg max-h-[80vh] object-contain"
              />
            )}

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

            {/* Cover image actions: assign to character */}
            {lightboxCoverCharImage && (
              <div className="mt-2 space-y-2">
                {myCharacters.length > 1 && (
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-gray-400 shrink-0">Assign to</label>
                    <select
                      className="bg-gray-800 border border-gray-700 rounded text-xs text-gray-300 px-2 py-1 focus:outline-none focus:border-gray-600"
                      value={assignCharId ?? ''}
                      onChange={(e) => setAssignCharId(e.target.value ? Number(e.target.value) : null)}
                    >
                      <option value="">Choose character…</option>
                      {myCharacters.map((c) => (
                        <option key={c.id} value={c.id}>{c.name}</option>
                      ))}
                    </select>
                  </div>
                )}
                {assignCoverErr && (
                  <p className="text-xs text-red-400">{assignCoverErr}</p>
                )}
                <div className="flex items-center justify-between gap-2">
                  {myCharacters.length > 1 && assignCharId === null ? (
                    <p className="text-xs text-gray-500">← Choose a character to apply</p>
                  ) : (
                    <span />
                  )}
                  <button
                    className="text-xs px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white transition-colors disabled:opacity-50 flex items-center gap-1.5"
                    disabled={assigningCover || assignCharId === null}
                    onClick={handleAssignCover}
                  >
                    {assignCoverDone ? (
                      <><Check className="w-3 h-3" />Cover set</>
                    ) : assigningCover ? (
                      'Setting…'
                    ) : myCharacters.length === 1 ? (
                      `Set as ${myCharacters[0].name}'s cover`
                    ) : (
                      'Set as cover'
                    )}
                  </button>
                </div>
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
        </div>
      )}
      </ErrorBoundary>
    </div>
  );
}

/** Human-readable label for when the weekly image allowance resets (B23). */
function formatResetTime(resetAt: string): string {
  const reset = new Date(resetAt);
  const now = new Date();
  const diffMs = reset.getTime() - now.getTime();
  if (diffMs <= 0) return 'very soon';
  const diffHours = Math.ceil(diffMs / (1000 * 60 * 60));
  if (diffHours <= 1) return 'in about an hour';
  if (diffHours < 24) return `in about ${diffHours} hours`;
  const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays === 1) return 'tomorrow';
  return `in ${diffDays} days`;
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
