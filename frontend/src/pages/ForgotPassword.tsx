import { useState } from 'react';
import { Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';

export default function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [resetUrl, setResetUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const res = await apiClient.forgotPassword(email);
      setSubmitted(true);
      if (res.reset_url) {
        setResetUrl(res.reset_url);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = async () => {
    if (!resetUrl) return;
    try {
      await navigator.clipboard.writeText(resetUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for browsers without clipboard API
      const input = document.createElement('input');
      input.value = resetUrl;
      document.body.appendChild(input);
      input.select();
      document.execCommand('copy');
      document.body.removeChild(input);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
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
          <h2 className="text-2xl font-bold mb-6">Forgot Password</h2>

          {submitted ? (
            <div>
              <div className="bg-green-900/20 border border-green-800 text-green-200 px-4 py-3 rounded mb-4">
                If an account with that email exists, we've sent a password reset link. Check your inbox.
              </div>

              {resetUrl && (
                <div className="bg-yellow-900/20 border border-yellow-800 rounded p-4 mb-4">
                  <p className="text-yellow-200 text-xs mb-2">Dev/admin mode only</p>
                  <button
                    onClick={handleCopy}
                    className="btn btn-primary w-full text-sm"
                  >
                    {copied ? 'Copied!' : 'Copy reset link'}
                  </button>
                </div>
              )}

              <p className="text-center text-gray-400 mt-4">
                <Link to="/login" className="text-owl-500 hover:text-owl-400">
                  Back to Login
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

              <p className="text-gray-400 text-sm mb-4">
                Enter your email address and we'll send you a link to reset your password.
              </p>

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

                <button type="submit" className="btn btn-primary w-full" disabled={loading}>
                  {loading ? 'Sending...' : 'Send Reset Link'}
                </button>
              </form>

              <p className="text-center text-gray-400 mt-4">
                Remember your password?{' '}
                <Link to="/login" className="text-owl-500 hover:text-owl-400">
                  Login
                </Link>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
