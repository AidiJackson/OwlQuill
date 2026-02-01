import { FileText } from 'lucide-react';
import type { CreationProfile } from '../shared/types';

interface Props {
  data: CreationProfile;
  onChange: (data: CreationProfile) => void;
  onFinish: () => void;
  onBack: () => void;
  saving: boolean;
}

export default function StepProfileDetails({ data, onChange, onFinish, onBack, saving }: Props) {
  const set = (field: keyof CreationProfile, value: string) =>
    onChange({ ...data, [field]: value });

  return (
    <div className="space-y-6">
      <div className="text-center space-y-2">
        <div className="mx-auto w-12 h-12 rounded-full bg-owl-600/20 flex items-center justify-center">
          <FileText className="w-6 h-6 text-owl-400" />
        </div>
        <h2 className="text-xl font-semibold text-gray-100">Complete the Profile</h2>
        <p className="text-sm text-gray-400">
          Add a bio, tags, and set visibility. You can always edit these later.
        </p>
      </div>

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1">Short Bio</label>
          <input
            className="input"
            placeholder="A one-line summary of your character"
            value={data.short_bio}
            onChange={(e) => set('short_bio', e.target.value)}
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1">Full Bio</label>
          <textarea
            className="textarea"
            rows={4}
            placeholder="Background, motivations, history…"
            value={data.long_bio}
            onChange={(e) => set('long_bio', e.target.value)}
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Tags</label>
            <input
              className="input"
              placeholder="e.g. warrior, mage, healer"
              value={data.tags}
              onChange={(e) => set('tags', e.target.value)}
            />
            <p className="text-xs text-gray-500 mt-1">Comma-separated</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Era / Setting</label>
            <input
              className="input"
              placeholder="e.g. Modern, Medieval"
              value={data.era}
              onChange={(e) => set('era', e.target.value)}
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1">Visibility</label>
          <select
            className="input"
            value={data.visibility}
            onChange={(e) => set('visibility', e.target.value)}
          >
            <option value="public">Public — visible to everyone</option>
            <option value="friends">Friends — visible to connections</option>
            <option value="private">Private — only you can see</option>
          </select>
        </div>
      </div>

      <div className="flex justify-between pt-2">
        <button className="btn btn-secondary" onClick={onBack} disabled={saving}>
          Back
        </button>
        <button
          className="btn btn-primary"
          onClick={onFinish}
          disabled={saving}
        >
          {saving ? 'Saving…' : 'Finish'}
        </button>
      </div>
    </div>
  );
}
