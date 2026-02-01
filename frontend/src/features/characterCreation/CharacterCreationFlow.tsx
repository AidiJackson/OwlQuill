import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Feather } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';

import StepBasics from './steps/StepBasics';
import StepPersonality from './steps/StepPersonality';
import StepGeneratePack from './steps/StepGeneratePack';
import StepSelect from './steps/StepSelect';
import StepLockConfirm from './steps/StepLockConfirm';
import StepProfileDetails from './steps/StepProfileDetails';

import { upsertDNA, resolveImageUrl } from './shared/api';
import type {
  CreationBasics,
  CreationSeeds,
  CreationProfile,
  IdentityPackResponse,
} from './shared/types';
import { STEP_LABELS } from './shared/types';

export default function CharacterCreationFlow() {
  const navigate = useNavigate();

  const [step, setStep] = useState(0);
  const [characterId, setCharacterId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const [basics, setBasics] = useState<CreationBasics>({
    name: '',
    age: '',
    species: '',
    gender_presentation: '',
  });

  const [seeds, setSeeds] = useState<CreationSeeds>({
    traits: [],
    vibeText: '',
  });

  const [generatedPack, setGeneratedPack] = useState<IdentityPackResponse | null>(null);
  const [selectedImageIndex, setSelectedImageIndex] = useState(0);

  const [profile, setProfile] = useState<CreationProfile>({
    short_bio: '',
    long_bio: '',
    tags: '',
    era: '',
    visibility: 'public',
  });

  // ── Transition: Personality → Generate (create character + upsert DNA)
  const handleAfterPersonality = async () => {
    setSaving(true);
    setError('');
    try {
      let cid = characterId;

      // Create character if not yet created
      if (!cid) {
        const character = await apiClient.createCharacter({
          name: basics.name,
          age: basics.age || undefined,
          species: basics.species || undefined,
        });
        cid = character.id;
        setCharacterId(cid);
      } else {
        // Update basics if character already exists
        await apiClient.updateCharacter(cid, {
          name: basics.name,
          age: basics.age || undefined,
          species: basics.species || undefined,
        });
      }

      // Upsert DNA
      await upsertDNA(cid, {
        species: basics.species || undefined,
        gender_presentation: basics.gender_presentation || undefined,
        visual_traits_json: {
          personality_traits: seeds.traits,
          vibe: seeds.vibeText,
        },
        structural_profile_json: {
          age_band: basics.age || undefined,
        },
      });

      setStep(2);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save character data.');
    } finally {
      setSaving(false);
    }
  };

  // ── Transition: Lock → Profile Details
  const handleLocked = () => {
    setStep(5);
  };

  // ── Transition: Profile Details → Done
  const handleFinish = async () => {
    if (!characterId) return;
    setSaving(true);
    setError('');
    try {
      // Set avatar to selected pack image
      const avatarUrl =
        generatedPack && generatedPack.images[selectedImageIndex]
          ? resolveImageUrl(generatedPack.images[selectedImageIndex].url)
          : undefined;

      await apiClient.updateCharacter(characterId, {
        short_bio: profile.short_bio || undefined,
        long_bio: profile.long_bio || undefined,
        tags: profile.tags || undefined,
        era: profile.era || undefined,
        visibility: profile.visibility,
        avatar_url: avatarUrl,
      });

      navigate('/characters');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save profile details.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <div className="border-b border-gray-800 bg-gray-900/50">
        <div className="max-w-xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2 text-gray-400">
            <Feather className="w-5 h-5 text-owl-400" />
            <span className="text-sm font-medium">New Character</span>
          </div>
          <button
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
            onClick={() => navigate('/characters')}
          >
            Cancel
          </button>
        </div>
      </div>

      {/* Step indicator */}
      <div className="max-w-xl mx-auto w-full px-4 pt-6 pb-2">
        <div className="flex items-center justify-center gap-1">
          {STEP_LABELS.map((label, i) => (
            <div key={label} className="flex items-center">
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium transition-colors ${
                  i === step
                    ? 'bg-owl-600 text-white'
                    : i < step
                      ? 'bg-owl-800 text-owl-300'
                      : 'bg-gray-800 text-gray-500'
                }`}
              >
                {i + 1}
              </div>
              {i < STEP_LABELS.length - 1 && (
                <div
                  className={`w-6 sm:w-10 h-0.5 transition-colors ${
                    i < step ? 'bg-owl-600' : 'bg-gray-800'
                  }`}
                />
              )}
            </div>
          ))}
        </div>
        <div className="text-center mt-1">
          <span className="text-xs text-gray-500">
            Step {step + 1}: {STEP_LABELS[step]}
          </span>
        </div>
      </div>

      {/* Global error */}
      {error && (
        <div className="max-w-xl mx-auto w-full px-4 pt-2">
          <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2 text-center">
            {error}
          </p>
        </div>
      )}

      {/* Step content */}
      <div className="flex-1 max-w-xl mx-auto w-full px-4 py-6">
        {step === 0 && (
          <StepBasics
            data={basics}
            onChange={setBasics}
            onNext={() => setStep(1)}
          />
        )}

        {step === 1 && (
          <StepPersonality
            data={seeds}
            onChange={setSeeds}
            onNext={handleAfterPersonality}
            onBack={() => setStep(0)}
            saving={saving}
          />
        )}

        {step === 2 && characterId && (
          <StepGeneratePack
            characterId={characterId}
            vibeText={seeds.vibeText}
            pack={generatedPack}
            onPackGenerated={(pack) => {
              setGeneratedPack(pack);
              setSelectedImageIndex(0);
            }}
            onNext={() => setStep(3)}
            onBack={() => setStep(1)}
          />
        )}

        {step === 3 && generatedPack && (
          <StepSelect
            pack={generatedPack}
            selectedIndex={selectedImageIndex}
            onSelect={setSelectedImageIndex}
            onNext={() => setStep(4)}
            onBack={() => setStep(2)}
          />
        )}

        {step === 4 && characterId && generatedPack && (
          <StepLockConfirm
            characterId={characterId}
            pack={generatedPack}
            selectedIndex={selectedImageIndex}
            onLocked={handleLocked}
            onBack={() => setStep(3)}
          />
        )}

        {step === 5 && (
          <StepProfileDetails
            data={profile}
            onChange={setProfile}
            onFinish={handleFinish}
            onBack={() => setStep(4)}
            saving={saving}
          />
        )}
      </div>
    </div>
  );
}
