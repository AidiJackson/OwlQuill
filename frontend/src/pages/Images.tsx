import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Image, X, Check } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { LibraryImage, UserImageRead } from '@/lib/types';

type Tab = 'characters' | 'covers';

export default function Images() {
  const [activeTab, setActiveTab] = useState<Tab>('characters');

  const [charImages, setCharImages] = useState<LibraryImage[]>([]);
  const [charLoading, setCharLoading] = useState(true);
  const [charError, setCharError] = useState('');

  const [coverImages, setCoverImages] = useState<UserImageRead[]>([]);
  const [coverLoading, setCoverLoading] = useState(true);
  const [coverError, setCoverError] = useState('');

  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [lightboxCoverId, setLightboxCoverId] = useState<number | null>(null);
  const [applyingCover, setApplyingCover] = useState(false);
  const [applyCoverDone, setApplyCoverDone] = useState(false);
  const [applyCoverErr, setApplyCoverErr] = useState('');

  const openLightbox = (url: string, coverId?: number) => {
    setLightboxUrl(url);
    setLightboxCoverId(coverId ?? null);
    setApplyCoverDone(false);
    setApplyCoverErr('');
  };

  const closeLightbox = () => {
    setLightboxUrl(null);
    setLightboxCoverId(null);
    setApplyCoverDone(false);
    setApplyCoverErr('');
  };

  const handleSetCover = async () => {
    if (!lightboxCoverId) return;
    setApplyingCover(true);
    setApplyCoverErr('');
    try {
      await apiClient.setMyProfileCover(lightboxCoverId);
      setApplyCoverDone(true);
      setTimeout(() => setApplyCoverDone(false), 2000);
    } catch (err) {
      setApplyCoverErr(err instanceof Error ? err.message : 'Failed to set cover.');
    } finally {
      setApplyingCover(false);
    }
  };

  useEffect(() => {
    apiClient
      .listMyCharacterImages()
      .then(setCharImages)
      .catch((err) => setCharError(err instanceof Error ? err.message : 'Failed to load'))
      .finally(() => setCharLoading(false));

    apiClient
      .listMyUserImages('profile_cover')
      .then(setCoverImages)
      .catch((err) => setCoverError(err instanceof Error ? err.message : 'Failed to load'))
      .finally(() => setCoverLoading(false));
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
                  ? 'border-owl-500 text-owl-300'
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
            {charError && (
              <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2">
                {charError}
              </p>
            )}
            {charLoading ? (
              <div className="flex items-center justify-center py-16 text-gray-400">Loading...</div>
            ) : charImages.length === 0 ? (
              <EmptyState message="No character images yet. Generate identity packs or moments from your character pages." />
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {charImages.map((img) => (
                  <button
                    key={img.id}
                    className="rounded-lg border border-gray-800 overflow-hidden bg-gray-900 hover:border-gray-600 transition-colors cursor-pointer text-left"
                    onClick={() => openLightbox(img.url)}
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
      {lightboxUrl && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
          onClick={closeLightbox}
        >
          <div className="relative max-w-3xl w-full mx-4" onClick={(e) => e.stopPropagation()}>
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
            {lightboxCoverId !== null && (
              <div className="flex items-center justify-between mt-2">
                <div>
                  {applyCoverErr && (
                    <p className="text-xs text-red-400">{applyCoverErr}</p>
                  )}
                </div>
                <button
                  className="text-xs px-3 py-1.5 rounded bg-owl-600 hover:bg-owl-500 text-white transition-colors disabled:opacity-50 flex items-center gap-1.5"
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
          </div>
        </div>
      )}
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center text-center py-16 space-y-4">
      <div className="w-14 h-14 rounded-full bg-owl-900/40 border border-owl-600/20 flex items-center justify-center">
        <Image className="w-7 h-7 text-owl-400" />
      </div>
      <h2 className="text-lg font-semibold text-gray-200">No images yet</h2>
      <p className="text-sm text-gray-400 max-w-sm">{message}</p>
    </div>
  );
}
