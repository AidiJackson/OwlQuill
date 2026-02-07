import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Image } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { LibraryImage } from '@/lib/types';

export default function Images() {
  const [images, setImages] = useState<LibraryImage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    apiClient
      .listLibraryImages()
      .then(setImages)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-400">
        Loading…
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <div className="border-b border-gray-800 bg-gray-900/50">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link to="/" className="text-gray-400 hover:text-gray-200 transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <span className="text-sm font-medium text-gray-300">Images</span>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-6">
        <p className="text-sm text-gray-400 mb-8">
          Create and reuse AI-generated images across OwlQuill.
        </p>

        {error && (
          <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2 mb-4">
            {error}
          </p>
        )}

        {images.length === 0 ? (
          <div className="flex flex-col items-center text-center py-16 space-y-4">
            <div className="w-14 h-14 rounded-full bg-owl-900/40 border border-owl-600/20 flex items-center justify-center">
              <Image className="w-7 h-7 text-owl-400" />
            </div>
            <h2 className="text-lg font-semibold text-gray-200">No images yet</h2>
            <p className="text-sm text-gray-400">
              Generate your first image to get started.
            </p>
            <Link
              to="/images/new"
              className="mt-2 px-5 py-2 bg-owl-600 hover:bg-owl-500 text-white text-sm font-medium rounded-lg transition-colors"
            >
              Generate image
            </Link>
            <p className="text-xs text-gray-500 mt-2">
              Uploads are disabled in beta. You can only use images generated in OwlQuill.
            </p>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between mb-4">
              <span className="text-sm text-gray-400">{images.length} image{images.length !== 1 ? 's' : ''}</span>
              <Link
                to="/images/new"
                className="btn btn-primary text-sm"
              >
                Generate image
              </Link>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {images.map((img) => (
                <div
                  key={img.id}
                  className="rounded-lg border border-gray-800 overflow-hidden bg-gray-900 group"
                >
                  <img
                    src={img.url}
                    alt={img.prompt_summary || 'Generated image'}
                    className="w-full aspect-[2/3] object-cover"
                  />
                  {img.prompt_summary && (
                    <p className="px-2 py-1.5 text-xs text-gray-400 truncate">
                      {img.prompt_summary}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
