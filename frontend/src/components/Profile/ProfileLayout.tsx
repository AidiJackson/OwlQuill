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
    <div className="min-h-screen bg-[#0F1419] relative">
      {/* Nav bar: absolutely positioned so it overlays the hero cover and scrolls with the page */}
      <header className="absolute top-0 left-0 right-0 z-50 bg-[#1A1D23]/60 backdrop-blur-xl border-b border-white/[0.06]">
        <div className="max-w-[1400px] mx-auto px-4 sm:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4 sm:gap-8">
              <button
                onClick={() => navigate('/')}
                className="flex items-center gap-3"
              >
                <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-quill-500 to-quill-700 flex items-center justify-center shadow-lg shadow-quill-500/20">
                  <Feather className="w-5 h-5 text-white" />
                </div>
                <span className="text-white tracking-tight font-semibold hidden sm:inline">OwlQuill</span>
              </button>

              <nav className="flex items-center gap-1">
                {navItems.map((item) => {
                  const Icon = item.icon;
                  return (
                    <button
                      key={item.id}
                      onClick={() => navigate(item.id)}
                      className="p-2.5 text-[#E8ECEF]/70 hover:text-white hover:bg-[#2D3139]/60 rounded-lg transition-all duration-200"
                      title={item.label}
                    >
                      <Icon className="w-5 h-5" />
                    </button>
                  );
                })}
              </nav>
            </div>

            <div className="flex items-center gap-4">
              {user && (
                <button
                  onClick={() => navigate(`/u/${user.username}`)}
                  className="w-10 h-10 rounded-full ring-2 ring-quill-500/40 overflow-hidden bg-[#2D3139] hover:ring-quill-500/60 transition-all"
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
        </div>
      </header>

      <main>
        <Outlet />
      </main>
    </div>
  );
}
