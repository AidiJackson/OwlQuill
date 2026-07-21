/**
 * S24AS — Identity Canon section for the Character Detail page.
 *
 * The v2 canon pack (13 cards + any mark detail crops) is stored as URLs inside
 * the identity-canon JSON, NOT as CharacterImage library rows, so the normal
 * image gallery never shows it. This component fetches the canon read-only and
 * renders the cards in a clearly labelled, separate "Identity Canon" section —
 * grouped Face / Body / Details. It makes no provider calls and never generates.
 */

import { useEffect, useState } from 'react';
import { ZoomIn, X } from 'lucide-react';
import { getIdentityCanon, resolveImageUrl } from '../shared/api';
import { V2_RECOVERY_SLOTS } from '../shared/canonRecovery';
import { V2_SLOT_LABELS } from '../shared/types';
import type { CharacterCanonRead } from '../shared/types';

interface Props {
  characterId: number;
}

interface CanonTile {
  key: string;
  label: string;
  url: string;
}

function slotUrl(
  canon: CharacterCanonRead,
  section: 'face' | 'body',
  field: string,
): string | null {
  const source = section === 'face' ? canon.face_canon : canon.body_canon;
  const value = source ? source[field] : null;
  return typeof value === 'string' && value.trim() !== '' ? value : null;
}

export default function IdentityCanonSection({ characterId }: Props) {
  const [canon, setCanon] = useState<CharacterCanonRead | null>(null);
  const [enlarged, setEnlarged] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    // Read-only fetch; failures degrade silently (the section simply hides).
    getIdentityCanon(characterId)
      .then((c) => { if (active) setCanon(c); })
      .catch(() => {});
    return () => { active = false; };
  }, [characterId]);

  if (!canon) return null;

  const faceTiles: CanonTile[] = [];
  const bodyTiles: CanonTile[] = [];
  for (const { slot, section, field } of V2_RECOVERY_SLOTS) {
    const url = slotUrl(canon, section, field);
    if (!url) continue;
    const tile: CanonTile = { key: slot, label: V2_SLOT_LABELS[slot] || slot, url };
    (section === 'face' ? faceTiles : bodyTiles).push(tile);
  }

  const markTiles: CanonTile[] = (canon.body_canon?.permanent_body_marks ?? [])
    .map((m) => {
      const url = m.detail_crop_url || m.reference_image_url || '';
      return url ? { key: m.id, label: m.label, url } : null;
    })
    .filter((t): t is CanonTile => t !== null);

  // Nothing generated yet → render nothing (no empty header).
  if (faceTiles.length === 0 && bodyTiles.length === 0 && markTiles.length === 0) {
    return null;
  }

  const renderGroup = (title: string, tiles: CanonTile[]) =>
    tiles.length > 0 && (
      <div className="space-y-2">
        <h3 className="text-xs font-medium text-ink-2 uppercase tracking-wide">{title}</h3>
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
          {tiles.map((tile) => {
            const url = resolveImageUrl(tile.url);
            return (
              <div key={tile.key} className="rounded-lg overflow-hidden border border-edge">
                <button
                  type="button"
                  onClick={() => setEnlarged(url)}
                  className="block w-full relative group"
                >
                  <img
                    src={url}
                    alt={tile.label}
                    className="w-full aspect-[2/3] object-cover"
                  />
                  <div className="absolute top-1.5 right-1.5 p-1 rounded-full bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
                    <ZoomIn className="w-3 h-3" />
                  </div>
                </button>
                <div className="px-1.5 py-1 text-center bg-surface">
                  <span className="text-[11px] text-ink-2 truncate block">{tile.label}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );

  return (
    <div className="border-t border-edge pt-6 space-y-4">
      <div>
        <h2 className="text-sm font-medium text-ink-2">Identity Canon</h2>
        <p className="text-xs text-ink-3 mt-0.5">
          The character's locked visual reference set.
        </p>
      </div>

      {renderGroup('Face', faceTiles)}
      {renderGroup('Body', bodyTiles)}
      {renderGroup('Details / Marks', markTiles)}

      {enlarged && (
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
          onClick={() => setEnlarged(null)}
        >
          <div className="relative max-w-md w-full" onClick={(e) => e.stopPropagation()}>
            <img src={enlarged} alt="Identity canon preview" className="w-full rounded-lg" />
            <button
              type="button"
              onClick={() => setEnlarged(null)}
              className="absolute top-3 right-3 p-1.5 rounded-full bg-black/60 text-white hover:bg-black/80 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
