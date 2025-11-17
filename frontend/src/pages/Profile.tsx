import { useState, useRef } from 'react';
import { useAuthStore } from '@/lib/store';
import { apiClient } from '@/lib/apiClient';

export default function Profile() {
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const [editing, setEditing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [formData, setFormData] = useState({
    display_name: user?.display_name || '',
    bio: user?.bio || '',
    avatar_url: user?.avatar_url || '',
  });

  const handleAvatarUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    // Validate file type
    if (!file.type.startsWith('image/')) {
      setUploadError('Please select an image file');
      return;
    }

    // Validate file size (5MB)
    if (file.size > 5 * 1024 * 1024) {
      setUploadError('File size must be less than 5MB');
      return;
    }

    setUploading(true);
    setUploadError(null);

    try {
      await apiClient.uploadUserAvatar(file);
      // Refresh user data
      const updated = await apiClient.getMe();
      setUser(updated);
    } catch (error) {
      console.error('Failed to upload avatar:', error);
      setUploadError(error instanceof Error ? error.message : 'Upload failed');
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleSave = async () => {
    try {
      const updated = await apiClient.updateMe(formData);
      setUser(updated);
      setEditing(false);
    } catch (error) {
      console.error('Failed to update profile:', error);
    }
  };

  if (!user) {
    return <div className="p-8">Loading...</div>;
  }

  return (
    <div className="max-w-2xl mx-auto p-8">
      <h1 className="text-3xl font-bold mb-8">Profile</h1>

      <div className="card">
        {/* Avatar display section */}
        <div className="flex items-center gap-6 mb-8 pb-6 border-b border-gray-700">
          <div className="w-24 h-24 rounded-full overflow-hidden bg-gray-700 flex-shrink-0">
            {(user.avatar_media_url || user.avatar_url) ? (
              <img
                src={user.avatar_media_url || user.avatar_url || ''}
                alt="Avatar"
                className="w-full h-full object-cover"
                onError={(e) => {
                  e.currentTarget.src = '';
                  e.currentTarget.style.display = 'none';
                }}
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-3xl text-gray-500">
                {user.username.charAt(0).toUpperCase()}
              </div>
            )}
          </div>
          <div className="flex-1">
            <h2 className="text-2xl font-bold">{user.display_name || user.username}</h2>
            <p className="text-gray-400 mb-2">@{user.username}</p>
            <div>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={handleAvatarUpload}
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="btn btn-sm btn-secondary"
              >
                {uploading ? 'Uploading...' : 'Upload Avatar'}
              </button>
              {uploadError && (
                <p className="text-red-400 text-sm mt-1">{uploadError}</p>
              )}
            </div>
          </div>
        </div>

        <div className="mb-6">
          <p className="text-sm text-gray-500">Email</p>
          <p className="text-lg">{user.email}</p>
        </div>

        {editing ? (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">Display Name</label>
              <input
                type="text"
                value={formData.display_name}
                onChange={(e) =>
                  setFormData({ ...formData, display_name: e.target.value })
                }
                className="input"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Avatar URL</label>
              <input
                type="url"
                value={formData.avatar_url}
                onChange={(e) =>
                  setFormData({ ...formData, avatar_url: e.target.value })
                }
                className="input"
                placeholder="https://..."
              />
              {formData.avatar_url && (
                <p className="text-xs text-gray-500 mt-1">Preview updated above</p>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Bio</label>
              <textarea
                value={formData.bio}
                onChange={(e) => setFormData({ ...formData, bio: e.target.value })}
                className="textarea"
                placeholder="Tell us about yourself..."
              />
            </div>

            <div className="flex gap-4">
              <button onClick={handleSave} className="btn btn-primary">
                Save
              </button>
              <button
                onClick={() => {
                  setEditing(false);
                  setFormData({
                    display_name: user.display_name || '',
                    bio: user.bio || '',
                    avatar_url: user.avatar_url || '',
                  });
                }}
                className="btn btn-secondary"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="mb-6">
              <p className="text-sm text-gray-500">Bio</p>
              <p className="text-gray-300 whitespace-pre-wrap">{user.bio || 'No bio yet'}</p>
            </div>

            <button onClick={() => setEditing(true)} className="btn btn-primary">
              Edit Profile
            </button>
          </>
        )}
      </div>
    </div>
  );
}
