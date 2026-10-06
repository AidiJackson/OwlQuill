/**
 * Tagged surface helpers (W-10A). Pure and DOM-free so they run in the node
 * vitest environment.
 */
import type { PostMention, ProfileTimelineItem, TaggedCharacter } from '@/lib/types';

function postIdOf(item: ProfileTimelineItem): number | undefined {
  const id = (item.payload as { id?: unknown }).id;
  return item.type === 'post' && typeof id === 'number' ? id : undefined;
}

/** The Tagged list after `characterId`'s tag is removed from `postId`.
 *
 *  The tag leaves the post's chips. The post itself leaves the list unless a
 *  legacy typed @mention of the same character still associates it — the
 *  server keeps such posts on the surface, so the client does too. */
export function afterTagRemoved(
  items: ProfileTimelineItem[],
  postId: number,
  characterId: number,
): ProfileTimelineItem[] {
  return items.flatMap((item) => {
    if (postIdOf(item) !== postId) return [item];
    const payload = item.payload as {
      tagged_characters?: TaggedCharacter[];
      mentions?: PostMention[];
    };
    const stillMentioned = (payload.mentions ?? []).some(
      (m) => m.target_type === 'character' && m.target_id === characterId,
    );
    if (!stillMentioned) return [];
    return [{
      ...item,
      payload: {
        ...item.payload,
        tagged_characters: (payload.tagged_characters ?? []).filter((t) => t.character_id !== characterId),
      },
    }];
  });
}
