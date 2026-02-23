import { useState, useEffect } from 'react';
import { Link, Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/lib/store';

export default function Layout() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [messagesSeen, setMessagesSeen] = useState(
    () => localStorage.getItem('ficshon.messages_seen') === 'true'
  );

  useEffect(() => {
    if (location.pathname.startsWith('/messages')) {
      localStorage.setItem('ficshon.messages_seen', 'true');
      setMessagesSeen(true);
    } else if (localStorage.getItem('ficshon.messages_seen') === 'true') {
      setMessagesSeen(true);
    }
  }, [location.pathname]);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const closeSidebar = () => setSidebarOpen(false);

  // Returns premium nav link classes based on active state
  function navCls(active: boolean) {
    return active
      ? 'flex items-center gap-2 h-10 px-4 rounded-xl bg-gray-900/60 text-gray-100 border border-emerald-500/20 transition-colors'
      : 'flex items-center gap-2 h-10 px-4 rounded-xl text-gray-300 hover:bg-gray-900/40 hover:text-gray-100 transition-colors';
  }

  const p = location.pathname;
  const isHome       = p === '/';
  const isRealms     = p.startsWith('/realms');
  const isChars      = p.startsWith('/characters');
  const isWorkspace  = p.startsWith('/workspace');
  const isImages     = p.startsWith('/images');
  const isMessages   = p.startsWith('/messages');
  const isProfile    = p.startsWith('/u/') || p === '/profile';

  const sidebarContent = (
    <>
      <div className="mb-8">
        <Link to="/" className="text-2xl font-bold text-emerald-400" onClick={closeSidebar}>
          Ficshon
        </Link>
      </div>

      <nav className="space-y-1">
        <Link
          to="/"
          className={navCls(isHome)}
          onClick={closeSidebar}
        >
          Home
        </Link>
        <Link
          to="/realms"
          className={navCls(isRealms)}
          onClick={closeSidebar}
        >
          Realms
        </Link>
        <Link
          to="/characters"
          className={navCls(isChars)}
          onClick={closeSidebar}
        >
          Characters
        </Link>
        <Link
          to="/workspace"
          className={navCls(isWorkspace)}
          onClick={closeSidebar}
        >
          WriteSpace
        </Link>
        <Link
          to="/images"
          className={navCls(isImages)}
          onClick={closeSidebar}
        >
          Images
        </Link>
        <Link
          to="/messages"
          className={navCls(isMessages)}
          onClick={closeSidebar}
        >
          Messages
          {!messagesSeen && (
            <span className="w-2 h-2 rounded-full bg-emerald-400 flex-shrink-0" />
          )}
        </Link>
        <Link
          to={user ? `/u/${user.username}` : '/profile'}
          className={navCls(isProfile)}
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
      {/* Desktop sidebar */}
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
          <Link to="/" className="ml-3 text-lg font-bold text-emerald-400">
            Ficshon
          </Link>
        </div>

        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
