import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type {
  CharacterHomePublic,
  CharacterHomePostPublic,
  CharacterImagePublic,
} from '@/lib/types';
import ErrorBoundary from '@/components/ErrorBoundary';
import ImageGrid from '@/features/images/components/ImageGrid';
import CharacterHomeHero from '@/features/characterHome/components/CharacterHomeHero';
import PublicPostCard from '@/features/characterHome/components/PublicPostCard';
import GalleryLightbox from '@/features/characterHome/components/GalleryLightbox';
import HomeFooter from '@/features/characterHome/components/HomeFooter';

/** How many posts a Home shows. Enough to read as a character's history rather
 *  than a marketing profile, and bounded because there is no pagination yet. */
const POST_LIMIT = 20;
const IMAGE_LIMIT = 24;

/**
 * The public Character Home — Ficshon's front door.
 *
 * This is the page a stranger reaches from a link pasted somewhere else. It
 * must read as "this is where Pan lives", not as the inside of an app they
 * have not joined. So it renders outside `Layout` and outside every route
 * guard: no sidebar, no nav, no notification bell, no acting-character
 * control, no owner affordances.
 *
 * **It deliberately never touches `useAuthStore`.** The backend endpoints take
 * no authentication dependency, so anonymous, signed-in stranger, creator and
 * admin all receive byte-identical responses. Reading auth state here would be
 * the one way to break that guarantee on the client, and a creator who cannot
 * see exactly what a visitor sees has no way to check what they published.
 *
 * LOADING is three parallel calls with different consequences. The profile
 * decides whether there is a page at all; posts and images are additive, and a
 * failure in either leaves the rest of the Home standing. A visitor should
 * never meet a broken panel on someone's front door.
 *
 * EMPTINESS is omitted, never announced. Every section disappears when it has
 * nothing to show, and no counts are rendered anywhere. A young Home should
 * look new, not unfinished — the opposite of the authenticated page, whose
 * "No Posts Yet" placeholders are correct guidance for an owner and quite
 * wrong for a stranger.
 */
export default function CharacterHome() {
  const { id } = useParams<{ id: string }>();
  const characterId = Number(id);

  const [character, setCharacter] = useState<CharacterHomePublic | null>(null);
  const [posts, setPosts] = useState<CharacterHomePostPublic[]>([]);
  const [images, setImages] = useState<CharacterImagePublic[]>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'missing' | 'error'>('loading');
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!Number.isFinite(characterId) || characterId <= 0) {
      setStatus('missing');
      return;
    }

    let cancelled = false;
    setStatus('loading');

    // The profile is the page. Posts and images settle independently so one
    // failing endpoint cannot take down a Home that otherwise renders.
    apiClient
      .getPublicCharacterHome(characterId)
      .then((home) => {
        if (cancelled) return;
        setCharacter(home);
        setStatus('ready');
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // 404 is the deliberate answer for unpublished, private AND
        // nonexistent — the server makes them indistinguishable so that walking
        // the id space reveals nothing, and this page must not undo that by
        // rendering three different states.
        const message = err instanceof Error ? err.message : '';
        setStatus(/not found/i.test(message) || /404/.test(message) ? 'missing' : 'error');
      });

    apiClient
      .getPublicCharacterHomePosts(characterId, POST_LIMIT)
      .then((rows) => { if (!cancelled) setPosts(rows); })
      .catch(() => { if (!cancelled) setPosts([]); });

    apiClient
      .getPublicCharacterHomeImages(characterId, IMAGE_LIMIT)
      .then((rows) => { if (!cancelled) setImages(rows); })
      .catch(() => { if (!cancelled) setImages([]); });

    return () => { cancelled = true; };
  }, [characterId, reloadKey]);

  if (status === 'loading') {
    return (
      <div className="min-h-screen bg-app flex items-center justify-center" role="status" aria-label="Loading">
        <div className="w-8 h-8 border-4 border-gem/25 border-t-gem rounded-full animate-spin" />
      </div>
    );
  }

  if (status === 'missing') {
    // Says nothing about why. Offering "sign in to see more" here would confirm
    // that something exists behind the 404, which is exactly what the server
    // refuses to confirm.
    return (
      <div className="min-h-screen bg-app flex flex-col items-center justify-center gap-3 px-6 text-center">
        <p className="font-serif text-xl text-ink">This character doesn&rsquo;t have a public home.</p>
        <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-3">Ficshon</p>
      </div>
    );
  }

  if (status === 'error' || !character) {
    return (
      <div className="min-h-screen bg-app flex flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-ink-2">Something went wrong loading this page.</p>
        <button
          onClick={() => setReloadKey((k) => k + 1)}
          className="px-4 py-2 rounded-lg text-sm font-medium bg-surface-elevated text-ink-2 hover:text-ink transition-colors"
        >
          Try again
        </button>
      </div>
    );
  }

  const hasAbout = !!(character.short_bio || character.long_bio || character.tags);
  const tags = character.tags
    ? character.tags.split(',').map((t) => t.trim()).filter(Boolean)
    : [];

  return (
    <div className="min-h-screen bg-app">
      <CharacterHomeHero character={character} />

      <div className="max-w-[1000px] mx-auto px-4 sm:px-8 py-10 sm:py-12 space-y-12 sm:space-y-16">
        {hasAbout && (
          <section className="max-w-3xl space-y-5">
            {character.short_bio && (
              <p className="font-serif text-lg sm:text-xl leading-[1.6] text-ink">
                {character.short_bio}
              </p>
            )}
            {character.long_bio && (
              <p className="fic-read fic-ooc whitespace-pre-wrap">{character.long_bio}</p>
            )}
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    className="px-2.5 py-1 bg-surface-elevated text-ink-2 font-mono text-[11px] rounded-full"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </section>
        )}

        {posts.length > 0 && (
          <section className="max-w-3xl">
            <h2 className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-3 mb-4">
              Latest from {character.name}
            </h2>
            {posts.map((post) => (
              <PublicPostCard key={post.id} post={post} />
            ))}
          </section>
        )}

        {images.length > 0 && (
          <section>
            <h2 className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-3 mb-4">
              Gallery
            </h2>
            <ErrorBoundary>
              {/* Two columns on a phone: this page is usually opened from a
                  shared link on a narrow screen, where the workspace's 3-up
                  grid gives tiles too small to be worth tapping. */}
              <ImageGrid images={images} columns="public" onImageClick={setLightboxIdx} />
            </ErrorBoundary>
          </section>
        )}
      </div>

      <HomeFooter characterName={character.name} />

      {lightboxIdx !== null && (
        <ErrorBoundary>
          <GalleryLightbox
            images={images}
            index={lightboxIdx}
            onClose={() => setLightboxIdx(null)}
          />
        </ErrorBoundary>
      )}
    </div>
  );
}
