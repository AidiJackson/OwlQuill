import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ShieldCheck, Loader2 } from 'lucide-react';
import type { IdentityPackResponse, CreationBasics } from '../shared/types';
import { acceptIdentityPack, resolveImageUrl } from '../shared/api';

interface Props {
  characterId: number;
  pack: IdentityPackResponse;
  selectedIndex: number;
  basics: CreationBasics;
}

export default function StepDossierLock({ characterId, pack, selectedIndex, basics }: Props) {
  const navigate = useNavigate();
  const [locking, setLocking] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    acceptIdentityPack(characterId, pack.pack_id)
      .catch((err) => {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : 'Lock failed';
          setError(msg.toLowerCase().includes('pack') ? 'Please generate your identity pack again.' : msg);
        }
      })
      .finally(() => {
        if (!cancelled) setLocking(false);
      });
    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const frontImg =
    pack.images.find((img) => (img.metadata_json?.pack_role as string) === 'anchor_front') ??
    pack.images[selectedIndex] ??
    pack.images[0];
  const torsoImg = pack.images.find(
    (img) => (img.metadata_json?.pack_role as string) === 'anchor_torso',
  );

  if (locking) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-20">
        <Loader2 className="w-8 h-8 text-emerald-400 animate-spin" />
        <p className="text-gray-400 text-sm">Locking identity…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4 text-center py-8">
        <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-3">{error}</p>
        <button className="btn btn-secondary" onClick={() => navigate('/characters')}>
          Back to Characters
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="text-center space-y-2">
        <div className="mx-auto w-14 h-14 rounded-full bg-emerald-500/20 flex items-center justify-center">
          <ShieldCheck className="w-7 h-7 text-emerald-400" />
        </div>
        <h2 className="text-xl font-semibold text-gray-100">Identity Locked</h2>
        <p className="text-sm text-gray-400">
          {basics.name ? `${basics.name}'s` : "Your character's"} visual identity is now locked and saved.
        </p>
      </div>

      {/* Dossier card */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <div className="flex items-start gap-4">
          {/* Front portrait */}
          {frontImg ? (
            <div className="w-24 rounded-lg overflow-hidden border border-gray-700 flex-shrink-0">
              <img
                src={resolveImageUrl(frontImg.url)}
                alt="Front portrait"
                className="w-full aspect-[2/3] object-cover"
              />
            </div>
          ) : (
            <div className="w-24 rounded-lg border border-gray-700 bg-gray-800 aspect-[2/3] flex-shrink-0" />
          )}

          {/* Info */}
          <div className="flex-1 min-w-0 space-y-1.5 pt-1">
            {basics.name && (
              <p className="text-sm font-semibold text-gray-100 truncate">{basics.name}</p>
            )}
            {basics.species && (
              <p className="text-xs text-gray-400 capitalize">{basics.species}</p>
            )}
            <p className="text-xs text-emerald-400 font-medium">Visual identity confirmed</p>
          </div>

          {/* Torso / full body */}
          {torsoImg && (
            <div className="w-16 rounded-lg overflow-hidden border border-gray-700 flex-shrink-0">
              <img
                src={resolveImageUrl(torsoImg.url)}
                alt="Full body"
                className="w-full aspect-[2/3] object-cover"
              />
            </div>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex flex-col gap-3 pt-2">
        <button
          className="btn btn-primary w-full"
          onClick={() => navigate(`/characters/${characterId}?created=1`)}
        >
          Continue to Ficshon
        </button>
        <button
          className="btn btn-secondary w-full"
          onClick={() => navigate(`/characters/${characterId}`)}
        >
          View Character
        </button>
      </div>
    </div>
  );
}
