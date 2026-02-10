import { useState } from 'react';
import { Link, useSearchParams, useNavigate } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';

export default function ResetPassword() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get('token') || '';

  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="max-w-md w-full">
          <div className="card">
            <h2 className="text-2xl font-bold mb-4">Invalid Link</h2>
            <p className="text-gray-400 mb-4">
              This password reset link is invalid or malformed. Please request a new one.
            </p>
            <Link to="/forgot-password" className="btn btn-primary w-full block text-center">
              Request New Link
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }

    setLoading(true);

    try {
      await apiClient.resetPassword(token, password);
      setSuccess(true);
      setTimeout(() => navigate('/login'), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reset password. The link may be expired or already used.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="max-w-md w-full">
        <div className="text-center mb-8">
          <h1 className="text-4xl font-bold text-owl-500 mb-2">OwlQuill</h1>
          <p className="text-gray-400">Roleplay-first social network</p>
        </div>

        <div className="card">
          <h2 className="text-2xl font-bold mb-6">Reset Password</h2>

          {success ? (
            <div>
              <div className="bg-green-900/20 border border-green-800 text-green-200 px-4 py-3 rounded mb-4">
                Password reset successfully! Redirecting to login...
              </div>
              <p className="text-center text-gray-400 mt-4">
                <Link to="/login" className="text-owl-500 hover:text-owl-400">
                  Go to Login
                </Link>
              </p>
            </div>
          ) : (
            <>
              {error && (
                <div className="bg-red-900/20 border border-red-800 text-red-200 px-4 py-3 rounded mb-4">
                  {error}
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-2">New Password</label>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="input"
                    required
                    minLength={8}
                    placeholder="At least 8 characters"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Confirm Password</label>
                  <input
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="input"
                    required
                    minLength={8}
                  />
                </div>

                <button type="submit" className="btn btn-primary w-full" disabled={loading}>
                  {loading ? 'Resetting...' : 'Reset Password'}
                </button>
              </form>

              <p className="text-center text-gray-400 mt-4">
                <Link to="/login" className="text-owl-500 hover:text-owl-400">
                  Back to Login
                </Link>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
