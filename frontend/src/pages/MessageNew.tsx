import { useSearchParams, Link } from 'react-router-dom';
import { ArrowLeft, MessageSquare } from 'lucide-react';

export default function MessageNew() {
  const [searchParams] = useSearchParams();
  const characterId = searchParams.get('characterId');

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <div className="border-b border-gray-800 bg-gray-900/50">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          {characterId ? (
            <Link
              to={`/characters/${characterId}`}
              className="text-gray-400 hover:text-gray-200 transition-colors"
            >
              <ArrowLeft className="w-5 h-5" />
            </Link>
          ) : (
            <Link
              to="/characters"
              className="text-gray-400 hover:text-gray-200 transition-colors"
            >
              <ArrowLeft className="w-5 h-5" />
            </Link>
          )}
          <span className="text-sm font-medium text-gray-300">Messages</span>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-16 flex flex-col items-center text-center space-y-5">
        <div className="w-14 h-14 rounded-full bg-owl-900/40 border border-owl-600/20 flex items-center justify-center">
          <MessageSquare className="w-7 h-7 text-owl-400" />
        </div>

        <div className="space-y-2">
          <h1 className="text-xl font-semibold text-gray-100">
            Messaging coming soon
          </h1>
          <p className="text-sm text-gray-400 max-w-sm leading-relaxed">
            Private messaging between writers is coming next.
            You'll be able to message character owners directly.
          </p>
        </div>

        {characterId && (
          <p className="text-xs text-gray-500">
            You're trying to message a character.
          </p>
        )}

        {characterId ? (
          <Link
            to={`/characters/${characterId}`}
            className="btn btn-secondary text-sm"
          >
            Back to character
          </Link>
        ) : (
          <Link
            to="/characters"
            className="btn btn-secondary text-sm"
          >
            Back to characters
          </Link>
        )}
      </div>
    </div>
  );
}
