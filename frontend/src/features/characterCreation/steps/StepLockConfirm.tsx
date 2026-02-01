import { useState } from 'react';
import { Lock, ShieldCheck } from 'lucide-react';
import type { IdentityPackResponse } from '../shared/types';
import { acceptIdentityPack, resolveImageUrl } from '../shared/api';

interface Props {
  characterId: number;
  pack: IdentityPackResponse;
  selectedIndex: number;
  onLocked: () => void;
  onBack: () => void;
}

export default function StepLockConfirm({
  characterId,
  pack,
  selectedIndex,
  onLocked,
  onBack,
}: Props) {
  const [locking, setLocking] = useState(false);
  const [error, setError] = useState('');

  const featured = pack.images[selectedIndex];

  const handleLock = async () => {
    setLocking(true);
    setError('');
    try {
      await acceptIdentityPack(characterId, pack.pack_id);
      onLocked();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Lock failed';
      if (msg.toLowerCase().includes('pack')) {
        setError('Please generate your identity pack again.');
      } else {
        setError(msg);
      }
    } finally {
      setLocking(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="text-center space-y-2">
        <div className="mx-auto w-12 h-12 rounded-full bg-amber-500/20 flex items-center justify-center">
          <Lock className="w-6 h-6 text-amber-400" />
        </div>
        <h2 className="text-xl font-semibold text-gray-100">Lock Visual Identity</h2>
      </div>

      {/* Preview */}
      <div className="flex justify-center">
        <div className="w-40 rounded-lg overflow-hidden border border-gray-700">
          <img
            src={resolveImageUrl(featured.url)}
            alt="Selected portrait"
            className="w-full aspect-[2/3] object-cover"
          />
        </div>
      </div>

      {/* Warning */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
        <div className="flex items-start gap-3">
          <ShieldCheck className="w-5 h-5 text-owl-400 mt-0.5 flex-shrink-0" />
          <div className="space-y-2 text-sm text-gray-300">
            <p>
              This will lock your character's visual identity. You can generate new images later,
              but this face will remain consistent.
            </p>
            <p className="text-gray-500">
              All three pack images will be saved as your character's canonical anchors.
            </p>
          </div>
        </div>
      </div>

      {error && (
        <p className="text-center text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2">
          {error}
        </p>
      )}

      <div className="flex justify-between pt-2">
        <button className="btn btn-secondary" onClick={onBack} disabled={locking}>
          Back
        </button>
        <button
          className="btn bg-amber-600 hover:bg-amber-700 text-white font-medium flex items-center gap-2"
          onClick={handleLock}
          disabled={locking}
        >
          <Lock className="w-4 h-4" />
          {locking ? 'Locking…' : 'Lock Identity'}
        </button>
      </div>
    </div>
  );
}
