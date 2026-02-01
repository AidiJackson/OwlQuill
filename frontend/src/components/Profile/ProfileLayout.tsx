import { Outlet, useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/lib/store';
import { Home, Users, Globe, BookOpen, MessageSquare, Settings, Feather } from 'lucide-react';

const navItems = [
  { id: '/', label: 'Feed', icon: Home },
  { id: '/characters', label: 'Characters', icon: Users },
  { id: '/realms', label: 'Realms', icon: Globe },
  { id: '/scenes', label: 'Scenes', icon: BookOpen },
  { id: '/messages', label: 'Messages', icon: MessageSquare },
  { id: '/profile', label: 'Settings', icon: Settings },
];

export default function ProfileLayout() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);

  return (
    <div className="min-h-screen bg-gray-950">
      <header className="sticky top-0 z-[999] bg-gray-950 border-b border-white/10 shadow-lg shadow-gray-950/50">
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <button
              onClick={() => navigate('/')}
              className="flex items-center gap-2"
            >
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-owl-500 to-owl-700 flex items-center justify-center">
                <Feather className="w-4 h-4 text-white" />
              </div>
              <span className="text-white font-semibold">OwlQuill</span>
            </button>

            <nav className="flex items-center gap-1">
              {navItems.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.id}
                    onClick={() => navigate(item.id)}
                    className="p-2.5 text-white/70 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                    title={item.label}
                  >
                    <Icon className="w-5 h-5" />
                  </button>
                );
              })}
            </nav>
          </div>

          <div className="flex items-center gap-3">
            {user && (
              <button
                onClick={() => navigate(`/u/${user.username}`)}
                className="w-9 h-9 rounded-full ring-2 ring-owl-500/50 overflow-hidden bg-gray-800"
              >
                {user.avatar_url ? (
                  <img
                    src={user.avatar_url}
                    alt={user.username}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-sm font-medium text-gray-400">
                    {user.username.charAt(0).toUpperCase()}
                  </div>
                )}
              </button>
            )}
          </div>
        </div>
      </header>

      <main>
        <Outlet />
      </main>
    </div>
  );
}
