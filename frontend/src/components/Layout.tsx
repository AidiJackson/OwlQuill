import { Link, Outlet, useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/lib/store';
import NotificationBell from './NotificationBell';

export default function Layout() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="min-h-screen flex">
      <aside className="w-64 bg-gray-900 border-r border-gray-800 p-4 flex flex-col">
        <div className="mb-8">
          <Link to="/" className="text-2xl font-bold text-owl-500">
            OwlQuill
          </Link>
        </div>

        {/* Notification Bell */}
        <div className="mb-4 px-2">
          <NotificationBell />
        </div>

        <nav className="space-y-2 flex-1">
          <Link
            to="/"
            className="block px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors"
          >
            Home
          </Link>
          <Link
            to="/realms"
            className="block px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors"
          >
            Realms
          </Link>
          <Link
            to="/characters"
            className="block px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors"
          >
            Characters
          </Link>
          <Link
            to="/discover"
            className="block px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors"
          >
            Discover
          </Link>
          <Link
            to="/profile"
            className="block px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors"
          >
            Profile
          </Link>
        </nav>

        {user && (
          <div className="mt-auto pt-8">
            <div className="px-4 py-2 text-sm text-gray-400">
              @{user.username}
            </div>
            <button
              onClick={handleLogout}
              className="w-full px-4 py-2 text-left rounded-lg hover:bg-gray-800 transition-colors text-red-400"
            >
              Logout
            </button>
          </div>
        )}
      </aside>

      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
