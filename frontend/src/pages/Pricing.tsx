import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/lib/store';
import { apiClient } from '@/lib/apiClient';
import type { Plan, CreditPack, CreditsResponse } from '@/lib/types';

export default function Pricing() {
  const navigate = useNavigate();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [creditPacks, setCreditPacks] = useState<CreditPack[]>([]);
  const [credits, setCredits] = useState<CreditsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [paymentsEnabled, setPaymentsEnabled] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const plansData = await apiClient.getPlans();
        setPlans(plansData.plans);
        setCreditPacks(plansData.credit_packs);
        setPaymentsEnabled(plansData.payments_enabled);

        if (isAuthenticated) {
          try {
            const creditsData = await apiClient.getCredits();
            setCredits(creditsData);
          } catch {
            // User might not be fully loaded yet
          }
        }
      } catch (error) {
        console.error('Failed to fetch plans:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [isAuthenticated]);

  const handlePlanAction = (planId: string) => {
    if (planId === 'free') {
      if (isAuthenticated) {
        navigate('/');
      } else {
        navigate('/register');
      }
    } else {
      // Creator or Studio - coming soon
      alert('Coming soon! Join the waitlist to be notified when this plan becomes available.');
    }
  };

  const handleBuyCredits = () => {
    alert('Coming soon! Credit packs will be available when payments are enabled.');
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-gray-400">Loading plans...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950">
      <div className="max-w-6xl mx-auto px-4 py-12">
        {/* Header */}
        <div className="text-center mb-12">
          <Link to="/" className="text-3xl font-bold text-owl-500 mb-4 inline-block">
            OwlQuill
          </Link>
          <h1 className="text-4xl font-bold mb-4">Simple, Honest Pricing</h1>
          <p className="text-xl text-gray-400 max-w-2xl mx-auto">
            No ads. No attention selling. Just tools for storytellers.
          </p>
          {!paymentsEnabled && (
            <div className="mt-4 inline-block px-4 py-2 bg-owl-900/30 border border-owl-700 rounded-lg text-owl-400 text-sm">
              Paid plans coming soon - Join the waitlist
            </div>
          )}
        </div>

        {/* Credits Display (if logged in) */}
        {isAuthenticated && credits && (
          <div className="mb-8 p-4 bg-gray-900 border border-gray-800 rounded-lg text-center">
            <span className="text-gray-400">Your AI Credits: </span>
            <span className="text-xl font-bold text-owl-400">{credits.balance}</span>
            {credits.monthly_allowance > 0 && (
              <span className="text-gray-500 ml-2">
                ({credits.monthly_allowance}/month on {credits.plan} plan)
              </span>
            )}
          </div>
        )}

        {!isAuthenticated && (
          <div className="mb-8 p-4 bg-gray-900 border border-gray-800 rounded-lg text-center text-gray-400">
            <Link to="/login" className="text-owl-400 hover:text-owl-300">Sign in</Link>
            {' '}to see your credits
          </div>
        )}

        {/* Plans Grid */}
        <div className="grid md:grid-cols-3 gap-6 mb-16">
          {plans.map((plan) => (
            <div
              key={plan.id}
              className={`card relative ${
                plan.is_popular
                  ? 'border-owl-500 ring-2 ring-owl-500/20'
                  : ''
              }`}
            >
              {plan.is_popular && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 bg-owl-500 text-white text-xs font-medium rounded-full">
                  Most Popular
                </div>
              )}

              <div className="p-6">
                <h3 className="text-2xl font-bold mb-2">{plan.name}</h3>
                <div className="text-3xl font-bold text-owl-400 mb-2">
                  {plan.price_label}
                </div>
                <p className="text-gray-400 text-sm mb-6">{plan.description}</p>

                <button
                  onClick={() => handlePlanAction(plan.id)}
                  className={`w-full py-3 px-4 rounded-lg font-medium transition-colors ${
                    plan.id === 'free'
                      ? 'btn btn-primary'
                      : 'bg-gray-800 hover:bg-gray-700 text-gray-300'
                  }`}
                >
                  {plan.id === 'free'
                    ? isAuthenticated
                      ? 'Current Plan'
                      : 'Start Free'
                    : 'Join Waitlist'}
                </button>

                <ul className="mt-6 space-y-3">
                  {plan.features.map((feature, idx) => (
                    <li key={idx} className="flex items-start gap-2">
                      <span
                        className={`mt-0.5 ${
                          feature.included ? 'text-green-500' : 'text-gray-600'
                        }`}
                      >
                        {feature.included ? (
                          <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                        ) : (
                          <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-11a1 1 0 10-2 0v3.586L7.707 9.293a1 1 0 00-1.414 1.414l3 3a1 1 0 001.414 0l3-3a1 1 0 00-1.414-1.414L11 10.586V7z" clipRule="evenodd" />
                          </svg>
                        )}
                      </span>
                      <span className={feature.included ? 'text-gray-300' : 'text-gray-500'}>
                        {feature.name}
                        {feature.limit && (
                          <span className="text-gray-500 text-sm"> ({feature.limit})</span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>

        {/* Credit Packs Section */}
        <div className="mb-16">
          <h2 className="text-2xl font-bold text-center mb-2">Need More Credits?</h2>
          <p className="text-gray-400 text-center mb-8">
            One-time credit packs for when you need extra AI generations. Credits never expire.
          </p>

          <div className="grid md:grid-cols-3 gap-4 max-w-3xl mx-auto">
            {creditPacks.map((pack) => (
              <div key={pack.id} className="card p-4 text-center">
                <h3 className="font-bold mb-1">{pack.name}</h3>
                <div className="text-2xl font-bold text-owl-400 mb-1">
                  {pack.credits} credits
                </div>
                <div className="text-gray-500 text-sm mb-3">{pack.price_label}</div>
                <button
                  onClick={handleBuyCredits}
                  className="w-full py-2 px-4 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm transition-colors"
                >
                  Coming Soon
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Trust Stance Footer */}
        <div className="text-center border-t border-gray-800 pt-8">
          <h3 className="text-lg font-semibold mb-2">Our Promise</h3>
          <p className="text-gray-400 mb-4">
            No ads. No selling attention. No behavioral tracking.
          </p>
          <Link
            to="/no-ads"
            className="text-owl-400 hover:text-owl-300 transition-colors"
          >
            Read our trust-first stance
          </Link>
        </div>
      </div>
    </div>
  );
}
