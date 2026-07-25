import { useNavigate } from 'react-router-dom';
import { Compass } from 'lucide-react';

/**
 * Shown when a Wanderer lands on a creator workspace by URL.
 *
 * A Wanderer is a complete, first-class role — not a half-finished creator.
 * So this panel does two things and deliberately not a third:
 *
 *   • names the destination honestly as a creator workspace (no blank screen,
 *     no confusing empty creator UI),
 *   • offers routes back into the consumer experience,
 *   • does NOT push "create a character" — that would frame browsing as an
 *     incomplete state to be fixed.
 */
interface Props {
  /** e.g. "The Image Library", "StoryLab". */
  workspaceName: string;
  /** One plain sentence on what the space is for. */
  description: string;
}

export default function WandererNotice({ workspaceName, description }: Props) {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="max-w-md w-full text-center space-y-6">
        <div className="w-14 h-14 rounded-2xl bg-gem-soft flex items-center justify-center mx-auto">
          <Compass className="w-7 h-7 text-gem" />
        </div>
        <div className="space-y-2">
          <h1 className="font-serif text-2xl text-ink">{workspaceName} is a creator workspace</h1>
          <p className="text-sm text-ink-2 leading-relaxed">{description}</p>
          <p className="text-sm text-ink-3 leading-relaxed">
            It isn't part of the Wanderer experience — but there's plenty to explore.
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-2">
          <button
            onClick={() => navigate('/')}
            className="px-4 py-2 rounded-lg text-sm font-semibold bg-gem text-gem-ink hover:bg-gem/90 transition-colors"
          >
            The Commons
          </button>
          <button
            onClick={() => navigate('/realms')}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-surface-elevated text-ink-2 hover:text-ink transition-colors"
          >
            Realms
          </button>
          <button
            onClick={() => navigate('/characters')}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-surface-elevated text-ink-2 hover:text-ink transition-colors"
          >
            Characters
          </button>
        </div>
      </div>
    </div>
  );
}
