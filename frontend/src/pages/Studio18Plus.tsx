import { Link } from 'react-router-dom';
import { ArrowLeft, Sparkles } from 'lucide-react';
import { useAuthStore } from '@/lib/store';

/**
 * Placeholder landing page for the upcoming 18+ Studio.
 * No generation happens here yet — this is a "coming soon" entry point that the
 * adult-adjacent nudge in the Image Generator links to.
 */
export default function Studio18Plus() {
  const isAdmin = useAuthStore((s) => !!s.user?.is_admin);

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <div className="border-b border-gray-800 bg-gray-900/50">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link to="/images" className="text-gray-400 hover:text-gray-200 transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <span className="text-sm font-medium text-gray-300">18+ Studio</span>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-10 space-y-6">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-fuchsia-900/30 border border-fuchsia-800/40 p-2.5">
            <Sparkles className="w-5 h-5 text-fuchsia-300" />
          </div>
          <h1 className="text-xl font-semibold text-gray-100">18+ Studio is coming soon</h1>
        </div>

        <p className="text-sm leading-relaxed text-gray-300">
          This mode will use stronger identity-locking technology designed for mature,
          swimwear, lingerie, underwear, and adult-adjacent character scenes while
          preserving canon consistency.
        </p>

        {isAdmin && (
          <div className="rounded-lg border border-gray-800 bg-gray-900/50 px-4 py-3">
            <p className="text-xs font-medium uppercase tracking-wide text-gray-500 mb-1">
              Admin / internal note
            </p>
            <p className="text-sm text-gray-400">
              Future direction: trained identity layer / LoRA / InstantID / PhotoMaker /
              IP-Adapter pipeline.
            </p>
          </div>
        )}

        <div className="pt-2">
          <Link to="/images" className="btn btn-secondary text-sm">
            Back to Images
          </Link>
        </div>
      </div>
    </div>
  );
}
