import { useState } from 'react';
import { Link, Outlet, useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/lib/store';

export default function Layout() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const closeSidebar = () => setSidebarOpen(false);

  const sidebarContent = (
    <>
      <div className="mb-8">
        <Link to="/" className="text-2xl font-bold text-owl-500" onClick={closeSidebar}>
          OwlQuill
        </Link>
      </div>

      <nav className="space-y-2">
        <Link
          to="/"
          className="block px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors"
          onClick={closeSidebar}
        >
          Home
        </Link>
        <Link
          to="/realms"
          className="block px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors"
          onClick={closeSidebar}
        >
          Realms
        </Link>
        <Link
          to="/characters"
          className="block px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors"
          onClick={closeSidebar}
        >
          Characters
        </Link>
        <Link
          to="/images"
          className="block px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors"
          onClick={closeSidebar}
        >
          Images
        </Link>
        <Link
          to={user ? `/u/${user.username}` : '/profile'}
          className="block px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors"
          onClick={closeSidebar}
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
    </>
  );

  return (
    <div className="min-h-screen flex">
      {/* Desktop sidebar — unchanged */}
      <aside className="hidden md:flex md:flex-col w-64 bg-gray-900 border-r border-gray-800 p-4">
        {sidebarContent}
      </aside>

      {/* Mobile backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={closeSidebar}
        />
      )}

      {/* Mobile slide-in sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 w-64 bg-gray-900 border-r border-gray-800 p-4 flex flex-col transform transition-transform duration-200 ease-in-out md:hidden ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {sidebarContent}
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Mobile top bar with hamburger */}
        <div className="md:hidden flex items-center p-3 bg-gray-900 border-b border-gray-800">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-1 text-gray-300 hover:text-white transition-colors"
            aria-label="Open menu"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-6 w-6"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <Link to="/" className="ml-3 text-lg font-bold text-owl-500">
            OwlQuill
          </Link>
        </div>

        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
