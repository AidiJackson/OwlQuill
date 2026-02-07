import { Link } from 'react-router-dom';
import { ArrowLeft, Image } from 'lucide-react';

export default function Images() {
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
      </div>
    </div>
  );
}
