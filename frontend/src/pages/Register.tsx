import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuthStore } from '@/lib/store';

export default function Register() {
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [inviteCode, setInviteCode] = useState('');
  const [error, setError] = useState('');
  const register = useAuthStore((state) => state.register);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    try {
      await register(email, username, password, inviteCode.trim().toUpperCase());
      // Identity-first, role-aware landing: a new account is a Wanderer — a
      // complete, permanent account type — so we drop them into The Commons to
      // browse characters, realms and public activity. The Commons shows no
      // character-creation prompt; the upgrade path is the restrained "Become a
      // Writer" entry in My Account, which leads to the Writer Unlock gate.
      // (Founder/seeder accounts are provisioned via scripts, not this form.)
      navigate('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="max-w-md w-full">
        <div className="flex flex-col items-center gap-4 mb-6">
          <img src="/brand/ficshon-mark-v1.png" alt="Ficshon" className="h-12 w-12 rounded-xl object-contain" />
          <h1 className="font-serif text-4xl font-semibold tracking-tight text-ink">Ficshon</h1>
          {/* Same tagline as Login; the beta notice stays as a secondary line
              rather than replacing it, so the positioning reads consistently
              across every public auth surface. */}
          <div className="space-y-1 text-center">
            <p className="text-ink-2">The social network for fictional characters</p>
            <p className="text-sm text-ink-3">Closed beta — invite required</p>
          </div>
        </div>

        <div className="card">
          <h2 className="text-2xl font-bold mb-6">Create Account</h2>

          {error && (
            <div className="bg-red-900/20 border border-red-800 text-red-200 px-4 py-3 rounded mb-4">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">Invite Code</label>
              <input
                type="text"
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)}
                className="input font-mono tracking-widest uppercase"
                placeholder="FICBETA-XXXX"
                required
                maxLength={100}
                autoComplete="off"
              />
            </div>

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
              <label className="block text-sm font-medium mb-2">Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="input"
                required
                minLength={3}
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
                minLength={8}
              />
            </div>

            <button type="submit" className="btn btn-primary w-full">
              Create Account
            </button>
          </form>

          <p className="text-center text-ink-2 mt-4">
            Already have an account?{' '}
            <Link to="/login" className="text-gem hover:opacity-80">
              Login
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
