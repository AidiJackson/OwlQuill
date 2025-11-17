import { useState, useEffect } from 'react';
import { apiClient } from '@/lib/apiClient';

interface Connection {
  id: number;
  username: string;
  display_name?: string;
  avatar_url?: string;
}

export default function Connections() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadConnections = async () => {
      try {
        const data = await apiClient.getMyConnections();
        setConnections(data);
      } catch (error) {
        console.error('Failed to load connections:', error);
      } finally {
        setLoading(false);
      }
    };

    loadConnections();
  }, []);

  const handleDisconnect = async (userId: number) => {
    try {
      await apiClient.disconnectFromUser(userId);
      setConnections(connections.filter(c => c.id !== userId));
    } catch (error) {
      console.error('Failed to disconnect:', error);
    }
  };

  if (loading) {
    return (
      <div className="p-8">
        <p className="text-gray-400">Loading...</p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-8">
      <h1 className="text-3xl font-bold mb-8">My Connections</h1>

      {connections.length === 0 ? (
        <div className="card text-center">
          <p className="text-gray-400 mb-4">No connections yet!</p>
          <p className="text-sm text-gray-500">
            Connect with other users to see their posts in your feed.
          </p>
        </div>
      ) : (
        <div className="grid gap-4">
          {connections.map((connection) => (
            <div key={connection.id} className="card flex items-center justify-between">
              <div className="flex items-center gap-4">
                {connection.avatar_url ? (
                  <img
                    src={connection.avatar_url}
                    alt={connection.username}
                    className="w-12 h-12 rounded-full object-cover"
                  />
                ) : (
                  <div className="w-12 h-12 rounded-full bg-gray-700 flex items-center justify-center">
                    <span className="text-xl font-bold text-gray-400">
                      {connection.username[0].toUpperCase()}
                    </span>
                  </div>
                )}
                <div>
                  <h3 className="font-semibold text-lg">
                    {connection.display_name || connection.username}
                  </h3>
                  <p className="text-sm text-gray-400">@{connection.username}</p>
                </div>
              </div>
              <button
                onClick={() => handleDisconnect(connection.id)}
                className="btn btn-secondary"
              >
                Disconnect
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
