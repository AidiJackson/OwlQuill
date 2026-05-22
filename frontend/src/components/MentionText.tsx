import { Link } from 'react-router-dom';
import type { PostMention } from '@/lib/types';

interface Props {
  text: string;
  mentions?: PostMention[];
  className?: string;
}

export default function MentionText({ text, mentions = [], className }: Props) {
  // Build lookup: "@alice" (lowercased) -> mention
  const lookup = new Map(
    mentions.filter(m => m.url).map(m => [m.mention_text.toLowerCase(), m])
  );

  // Split by @word boundaries, keeping the delimiters
  const parts = text.split(/(@[A-Za-z0-9_]+)/g);

  return (
    <span className={className}>
      {parts.map((part, i) => {
        if (part.startsWith('@')) {
          const resolved = lookup.get(part.toLowerCase());
          if (resolved?.url) {
            return (
              <Link
                key={i}
                to={resolved.url}
                className="text-violet-400 hover:text-violet-300 hover:underline"
                onClick={e => e.stopPropagation()}
              >
                {part}
              </Link>
            );
          }
          // Unresolved mention — highlight without link
          return (
            <span key={i} className="text-violet-400/60">
              {part}
            </span>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </span>
  );
}
