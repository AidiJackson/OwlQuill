import { useState } from 'react';
import { useAuthStore } from '@/lib/store';
import { apiClient } from '@/lib/apiClient';

export default function Profile() {
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const [editing, setEditing] = useState(false);
  const [formData, setFormData] = useState({
    display_name: user?.display_name || '',
    bio: user?.bio || '',
    avatar_url: user?.avatar_url || '',
  });

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
        <div className="mb-6">
          <p className="text-sm text-gray-500">Username</p>
          <p className="text-lg">@{user.username}</p>
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
              <label className="block text-sm font-medium mb-2">Bio</label>
              <textarea
                value={formData.bio}
                onChange={(e) => setFormData({ ...formData, bio: e.target.value })}
                className="textarea"
                placeholder="Tell us about yourself..."
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
              <p className="text-sm text-gray-500">Display Name</p>
              <p className="text-lg">{user.display_name || 'Not set'}</p>
            </div>

            <div className="mb-6">
              <p className="text-sm text-gray-500">Bio</p>
              <p className="text-gray-300">{user.bio || 'No bio yet'}</p>
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
