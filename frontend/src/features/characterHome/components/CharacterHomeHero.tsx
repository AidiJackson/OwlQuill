import { Feather } from 'lucide-react';
import type { CharacterHomePublic } from '@/lib/types';
import { avatarTransformStyle, coverObjectPosition } from '@/lib/media';

/**
 * The one species that says nothing about a character.
 *
 * Every other value here — Fae, revenant, wolf — is a fact about who this is.
 * "human" is the default answer, and standing alone above a name it reads as a
 * field that was filled in rather than a character that was described.
 *
 * Compared case-insensitively and trimmed, because this is creator-entered
 * free text and "Human" is the same non-statement as "human".
 */
const GENERIC_SPECIES = 'human';

/**
 * The establishing shot of a public Character Home.
 *
 * Adapted from the authenticated character page's hero so a visitor and a
 * creator meet the same character in the same visual language — same cover
 * treatment, same gradient fade, same serif headline, same avatar framing. What
 * is gone is everything that only makes sense to an owner: the cover picker,
 * the reposition control, the avatar camera button, the stat row, the tabs.
 *
 * No counts are rendered at all. A "0 Posts" figure on a public page advertises
 * emptiness to precisely the visitor who should not be told about it, and a
 * young Home should read as new rather than unfinished.
 *
 * Everything below the name is conditional. A character with only a name gets a
 * cover, a portrait and a headline — sparse, but composed.
 */
export default function CharacterHomeHero({ character }: { character: CharacterHomePublic }) {
  // role · species · era, from whichever the server actually sent. The whole
  // line disappears when all three are empty rather than leaving a gap.
  const metaParts = [character.role, character.species, character.era].filter(Boolean);

  // ...and it disappears in one more case: when the only thing left to say is
  // that the character is human. A lone "HUMAN" over the name is a database
  // value wearing a label, and the hero is better with nothing there than with
  // that. Deliberately narrow — the suppression needs species to be the ONLY
  // populated value, so "immortal king · human · timeless" is untouched, and it
  // keys on the generic value alone, so a distinctive species still introduces
  // a character that has nothing else filled in yet.
  const isLoneGenericSpecies =
    metaParts.length === 1 &&
    !!character.species &&
    character.species.trim().toLowerCase() === GENERIC_SPECIES;

  const metaLine = isLoneGenericSpecies ? '' : metaParts.join(' · ');

  return (
    <section className="relative">
      {/* Cover backdrop — spans the full hero */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        {character.cover_url ? (
          <img
            src={character.cover_url}
            alt=""
            aria-hidden="true"
            className="absolute inset-0 w-full h-full object-cover"
            style={{
              objectPosition: coverObjectPosition(
                character.cover_position_x,
                character.cover_position_y,
              ),
            }}
            draggable={false}
          />
        ) : (
          /* Designed fallback — quiet gem atmosphere, never borrowed imagery.
             A Home without a cover should still look composed. */
          <div
            className="absolute inset-0"
            style={{
              background:
                'radial-gradient(ellipse 70% 90% at 20% 0%, rgb(var(--gem) / 0.16) 0%, transparent 60%), radial-gradient(ellipse 60% 80% at 90% 100%, rgb(var(--gem) / 0.08) 0%, transparent 55%), var(--surface)',
            }}
          >
            <Feather className="absolute top-[24%] right-8 w-16 h-16 text-ink-3/25" />
          </div>
        )}
        {/* Cinematic fade into the page background */}
        <div className="cover-gradient absolute inset-0" />
      </div>

      <div className="relative max-w-[1000px] mx-auto px-4 sm:px-8">
        {/* Establishing space — pure cover, nothing competing with the image.
            Taller than the authenticated page's equivalent because there is no
            app chrome above it to share the screen with. */}
        <div className="h-[38vh] min-h-[220px] sm:h-[48vh] sm:min-h-[360px] lg:h-[54vh] max-h-[640px]" />

        <div className="xl:-ml-10 2xl:-ml-16">
          {metaLine && (
            <span className="hero-text-glow block font-mono text-[11px] uppercase tracking-[0.14em] text-ink-2 mb-2">
              {metaLine}
            </span>
          )}

          {/* The character's name IS the headline. The lower clamp floor is
              smaller than the authenticated page's because this page is opened
              from a shared link, most often on a phone. */}
          <h1
            className="hero-text-glow font-serif font-semibold text-ink leading-[0.98] tracking-[-0.02em] break-words"
            style={{ fontSize: 'clamp(30px, 8vw, 72px)' }}
          >
            {character.name}
          </h1>

          {character.alias && (
            <p className="hero-text-glow mt-2 font-serif text-lg sm:text-xl text-ink-2 italic">
              {character.alias}
            </p>
          )}

          {/* Portrait, lower-left, anchoring the hero. `relative` is
              load-bearing: the absolutely-positioned image needs this
              overflow-hidden box as its containing block, or a scaled avatar
              escapes the clip and spills over the content below. */}
          <div className="mt-6 sm:mt-9">
            <div className="relative w-[88px] h-[88px] sm:w-28 sm:h-28 md:w-32 md:h-32 rounded-2xl overflow-hidden border-[3px] border-app shadow-[0_0_0_1px_var(--border-md),0_8px_28px_rgba(0,0,0,0.4)] bg-surface-elevated">
              {character.avatar_url ? (
                <img
                  src={character.avatar_url}
                  alt={character.name}
                  className="absolute inset-0 w-full h-full object-cover pointer-events-none"
                  style={avatarTransformStyle(
                    character.avatar_scale,
                    character.avatar_position_x,
                    character.avatar_position_y,
                  )}
                  onError={(e) => { e.currentTarget.style.display = 'none'; }}
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center font-serif text-3xl font-semibold text-gem bg-gem-soft">
                  {character.name.charAt(0).toUpperCase()}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
