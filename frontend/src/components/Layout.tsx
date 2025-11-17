import { Link, Outlet, useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/lib/store';

export default function Layout() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="min-h-screen flex flex-col md:flex-row">
      <aside className="w-full md:w-64 bg-gray-900 border-b md:border-r md:border-b-0 border-gray-800 p-4">
        <div className="mb-4 md:mb-8">
          <Link to="/" className="text-2xl font-bold text-owl-500">
            OwlQuill
          </Link>
        </div>

        <nav className="flex md:flex-col gap-1 md:gap-2 overflow-x-auto md:overflow-x-visible">
          <Link
            to="/"
            className="block px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors whitespace-nowrap"
          >
            Home
          </Link>
          <Link
            to="/discover"
            className="block px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors whitespace-nowrap"
          >
            Discover
          </Link>
          <Link
            to="/realms"
            className="block px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors whitespace-nowrap"
          >
            Realms
          </Link>
          <Link
            to="/characters"
            className="block px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors whitespace-nowrap"
          >
            Characters
          </Link>
          <Link
            to="/profile"
            className="block px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors whitespace-nowrap"
          >
            Profile
          </Link>
        </nav>

        {user && (
          <div className="hidden md:block mt-auto pt-8">
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
