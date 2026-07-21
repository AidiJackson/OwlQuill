import type { StorySpaceChannel } from '@/lib/types';

const CHANNEL_ICONS: Record<string, string> = {
  story: '📖',
  chat: '💬',
  planning: '🛠',
};

interface Props {
  channels: StorySpaceChannel[];
  activeChannelId: number | null;
  onSelect: (channel: StorySpaceChannel) => void;
}

export default function ChannelList({ channels, activeChannelId, onSelect }: Props) {
  return (
    <div className="py-2">
      <p className="px-4 py-2 text-[10px] font-semibold uppercase tracking-widest text-ink-3">
        Channels
      </p>
      <ul className="space-y-0.5 px-2">
        {channels.map((ch) => {
          const active = ch.id === activeChannelId;
          return (
            <li key={ch.id}>
              <button
                type="button"
                onClick={() => onSelect(ch)}
                className={`w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                  active
                    ? 'bg-surface-elevated text-ink'
                    : 'text-ink-3 hover:bg-surface hover:text-ink-2'
                }`}
              >
                <span className="text-base leading-none select-none" aria-hidden="true">
                  {CHANNEL_ICONS[ch.channel_type] ?? '#'}
                </span>
                <span className="truncate">{ch.name}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
