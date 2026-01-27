import { Link } from 'react-router-dom';

export default function NoAds() {
  return (
    <div className="min-h-screen bg-gray-950">
      <div className="max-w-3xl mx-auto px-4 py-12">
        {/* Header */}
        <div className="text-center mb-12">
          <Link to="/" className="text-3xl font-bold text-owl-500 mb-4 inline-block">
            OwlQuill
          </Link>
          <h1 className="text-4xl font-bold mb-4">Our Trust-First Stance</h1>
          <p className="text-xl text-gray-400">
            Your creative work belongs to you, and your attention is not for sale.
          </p>
        </div>

        {/* Main Content */}
        <div className="space-y-8">
          {/* No Ads Section */}
          <section className="card p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-900/30 flex items-center justify-center">
                <svg className="w-5 h-5 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
                </svg>
              </div>
              <h2 className="text-2xl font-bold">No Ads. Ever.</h2>
            </div>
            <ul className="space-y-3 text-gray-300">
              <li className="flex items-start gap-2">
                <span className="text-red-400 mt-1">-</span>
                We will never display advertisements on OwlQuill
              </li>
              <li className="flex items-start gap-2">
                <span className="text-red-400 mt-1">-</span>
                We will never sell your attention to advertisers
              </li>
              <li className="flex items-start gap-2">
                <span className="text-red-400 mt-1">-</span>
                We will never interrupt your creative flow with promotional content
              </li>
            </ul>
          </section>

          {/* No Tracking Section */}
          <section className="card p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-blue-900/30 flex items-center justify-center">
                <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                </svg>
              </div>
              <h2 className="text-2xl font-bold">No Behavioral Tracking</h2>
            </div>
            <ul className="space-y-3 text-gray-300">
              <li className="flex items-start gap-2">
                <span className="text-blue-400 mt-1">-</span>
                We do not track your browsing behavior for marketing purposes
              </li>
              <li className="flex items-start gap-2">
                <span className="text-blue-400 mt-1">-</span>
                We do not build advertising profiles on our users
              </li>
              <li className="flex items-start gap-2">
                <span className="text-blue-400 mt-1">-</span>
                We do not sell or share your data with third-party advertisers
              </li>
            </ul>
          </section>

          {/* No Attention Selling Section */}
          <section className="card p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-green-900/30 flex items-center justify-center">
                <svg className="w-5 h-5 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <h2 className="text-2xl font-bold">No Selling Attention</h2>
            </div>
            <ul className="space-y-3 text-gray-300">
              <li className="flex items-start gap-2">
                <span className="text-green-400 mt-1">-</span>
                Your time on OwlQuill is yours to spend creating
              </li>
              <li className="flex items-start gap-2">
                <span className="text-green-400 mt-1">-</span>
                We will never manipulate engagement metrics to increase "time on site" for ad revenue
              </li>
              <li className="flex items-start gap-2">
                <span className="text-green-400 mt-1">-</span>
                Our success is measured by the stories you tell, not the ads you see
              </li>
            </ul>
          </section>

          {/* How We Sustain Section */}
          <section className="card p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-owl-900/30 flex items-center justify-center">
                <svg className="w-5 h-5 text-owl-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" />
                </svg>
              </div>
              <h2 className="text-2xl font-bold">How We Sustain OwlQuill</h2>
            </div>
            <p className="text-gray-400 mb-4">Instead of ads, we offer:</p>
            <ul className="space-y-3 text-gray-300">
              <li className="flex items-start gap-2">
                <span className="text-owl-400 mt-1">1.</span>
                <div>
                  <strong>Optional Subscriptions</strong>
                  <span className="text-gray-400"> - Creator and Studio tiers with enhanced features</span>
                </div>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-owl-400 mt-1">2.</span>
                <div>
                  <strong>AI Credit Packs</strong>
                  <span className="text-gray-400"> - One-time purchases for additional AI generation credits</span>
                </div>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-owl-400 mt-1">3.</span>
                <div>
                  <strong>Community Support</strong>
                  <span className="text-gray-400"> - Direct support from users who believe in ad-free creative spaces</span>
                </div>
              </li>
            </ul>
          </section>

          {/* Why This Matters */}
          <section className="text-center py-8 border-t border-gray-800">
            <h2 className="text-2xl font-bold mb-4">Why This Matters</h2>
            <p className="text-gray-300 text-lg max-w-2xl mx-auto mb-6">
              Writers and creators deserve a space free from algorithmic manipulation and advertising pressure.
              OwlQuill exists to serve storytellers, not advertisers.
            </p>
            <p className="text-owl-400 text-xl font-medium">
              Your stories. Your data. Your attention. All yours.
            </p>
          </section>

          {/* CTA */}
          <div className="text-center">
            <Link
              to="/pricing"
              className="btn btn-primary inline-block mr-4"
            >
              View Pricing
            </Link>
            <Link
              to="/"
              className="btn btn-secondary inline-block"
            >
              Back to Home
            </Link>
          </div>
        </div>

        {/* Footer Note */}
        <div className="mt-12 text-center text-sm text-gray-500">
          This stance is foundational to OwlQuill and will not change.
        </div>
      </div>
    </div>
  );
}
