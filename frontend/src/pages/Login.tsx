import { useState } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useAuthStore } from '@/lib/store';
import { returnToFromState } from '@/lib/returnTo';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const login = useAuthStore((state) => state.login);
  const navigate = useNavigate();
  const location = useLocation();
  // Where the redirect that sent them here was headed. Read once, at render,
  // so the destination is fixed before the form is submitted; validated, so an
  // external URL can never be navigated to. Absent or unsafe becomes '/'.
  const returnTo = returnToFromState(location.state);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    try {
      await login(email, password);
      // `replace` so the back button returns to wherever they were before the
      // interrupted deep link, not to a login form they have already used.
      navigate(returnTo, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="max-w-md w-full">
        <div className="flex flex-col items-center gap-4 mb-6">
          <img src="/brand/ficshon-mark-v1.png" alt="Ficshon" className="h-12 w-12 rounded-xl object-contain" />
          <h1 className="font-serif text-4xl font-semibold tracking-tight text-ink">Ficshon</h1>
          <p className="text-ink-2">The social network for fictional characters</p>
        </div>

        <div className="card">
          <h2 className="text-2xl font-bold mb-6">Login</h2>

          {error && (
            <div className="bg-red-900/20 border border-red-800 text-red-200 px-4 py-3 rounded mb-4">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input"
                required
              />
            </div>

            <button type="submit" className="btn btn-primary w-full">
              Login
            </button>
          </form>

          <p className="text-center mt-3">
            <Link to="/forgot-password" className="text-sm text-ink-2 hover:text-gem">
              Forgot password?
            </Link>
          </p>

          <p className="text-center text-ink-2 mt-4">
            Don't have an account?{' '}
            <Link to="/register" className="text-gem hover:opacity-80">
              Register
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
