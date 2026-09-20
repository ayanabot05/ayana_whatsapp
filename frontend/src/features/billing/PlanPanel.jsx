import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Crown, Ticket, CreditCard, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '@/lib/api';
import { PricingCards } from '@/components/PricingCards';
import { Button } from '@/components/ui/button';
import { CheckoutDialog } from './CheckoutDialog';
import { SubscribeDialog } from './SubscribeDialog';
import { BillingStatus } from './BillingStatus';
import { SubscriptionStatus } from './SubscriptionStatus';

// Toggle between one-time payment and auto-renewing subscription
const PaymentModeToggle = ({ mode, onChange }) => (
  <div className="flex rounded-xl border border-ayana-line overflow-hidden text-sm w-fit" data-testid="payment-mode-toggle">
    <button
      onClick={() => onChange('once')}
      className={`px-4 py-2 flex items-center gap-2 transition-colors ${mode === 'once' ? 'bg-ayana-primary text-white' : 'text-ayana-secondary hover:bg-ayana-bg'}`}
      data-testid="mode-once"
    >
      <CreditCard className="w-3.5 h-3.5" />
      Pay once
    </button>
    <button
      onClick={() => onChange('subscribe')}
      className={`px-4 py-2 flex items-center gap-2 transition-colors ${mode === 'subscribe' ? 'bg-ayana-primary text-white' : 'text-ayana-secondary hover:bg-ayana-bg'}`}
      data-testid="mode-subscribe"
    >
      <RefreshCw className="w-3.5 h-3.5" />
      Subscribe (auto-renews)
    </button>
  </div>
);

export const PlanPanel = ({ plans, currencies, planId, plan, usage, circle, reload }) => {
  const [selection, setSelection] = useState(null);
  const [payMode, setPayMode] = useState('subscribe'); // default to subscribe
  const client = useQueryClient();

  const { data: access } = useQuery({
    queryKey: ['billing-access'],
    queryFn: () => api.get('/payment/access').then(r => r.data),
  });

  const completed = async result => {
    setSelection(null);
    const isSubscription = result.status === 'authenticated' || result.status === 'subscribed';
    const isTrial = result.status === 'trial';
    const isSponsored = result.status === 'sponsored';
    toast.success(
      isSponsored ? 'Lifetime Raksha access enabled — completely free.' :
      isTrial ? 'Trial plan selected.' :
      isSubscription ? 'Payment authorization received. Subscription status is being verified.' :
      'Payment captured and verified.'
    );
    await Promise.all([
      reload(),
      client.invalidateQueries({ queryKey: ['billing-access'] }),
      client.invalidateQueries({ queryKey: ['billing-orders'] }),
      client.invalidateQueries({ queryKey: ['billing-subscriptions'] }),
    ]);
  };

  if (circle?.role === 'member') {
    return (
      <p className="rounded-2xl bg-white p-6 border border-ayana-line text-sm" data-testid="billing-owner-only">
        Only the account owner manages billing. You are covered under {circle.owner?.name}'s {plan?.name} plan.
      </p>
    );
  }

  const isLifetime = access?.lifetime;
  const onSelect = isLifetime ? undefined : (id, billing, currency) => setSelection({ plan: id, billing, currency });

  return (
    <div className="space-y-5 max-w-4xl" data-testid="plan-panel">
      <BillingStatus />
      <SubscriptionStatus />

      <section className="bg-white rounded-2xl border border-ayana-line p-5 space-y-3" data-testid="plan-usage">
        <h2 className="font-display text-lg flex items-center gap-2">
          <Crown className="w-5 h-5 text-ayana-primary" />
          Your care plan
        </h2>
        <p className="text-sm text-ayana-secondary" data-testid="plan-current-limits">
          {usage.parents ?? 0}/{plan?.limits?.parents ?? '—'} parents · {usage.family_members_used ?? 0}/{plan?.limits?.family_members ?? 0} additional family members
        </p>
        {!isLifetime && (
          <p className="text-sm text-ayana-secondary" data-testid="plan-prepaid-policy">
            {payMode === 'subscribe'
              ? 'Subscriptions auto-renew each period. Cancel anytime — access continues until end of paid period.'
              : 'One-time payments are prepaid. Renew manually; no automatic charges.'}
          </p>
        )}
        {!isLifetime && (
          <Button variant="outline" onClick={() => { setPayMode('once'); setSelection({ plan: 'raksha', billing: 'year', currency: currencies?.[0]?.code || currencies?.[0] }); }} data-testid="redeem-lifetime-code">
            <Ticket className="w-4 h-4 mr-2" />
            Redeem a free-access code
          </Button>
        )}
      </section>

      <section className="bg-white rounded-2xl border border-ayana-line p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-lg" data-testid="plan-purchase-title">
            {isLifetime ? 'Your lifetime plan is covered' : 'Choose or change your plan'}
          </h2>
          {!isLifetime && (
            <PaymentModeToggle mode={payMode} onChange={setPayMode} />
          )}
        </div>

        {!isLifetime && payMode === 'subscribe' && (
          <p className="text-xs text-ayana-secondary">
            <RefreshCw className="inline w-3 h-3 mr-1" />
            Subscribe for automatic renewal. Monthly plans charge each month; annual plans charge once a year.
          </p>
        )}

        <PricingCards
          plans={plans}
          currencies={currencies}
          selectedPlan={planId}
          onSelect={onSelect}
          actionLabel={p => {
            if (isLifetime) return 'Covered';
            if (payMode === 'subscribe') return p.id === planId ? 'Manage / switch' : 'Subscribe';
            return p.id === planId ? 'Renew / apply coupon' : 'Choose plan';
          }}
          compact
        />
      </section>

      {/* One-time payment dialog */}
      {payMode === 'once' && (
        <CheckoutDialog
          selection={selection}
          onClose={() => setSelection(null)}
          onComplete={completed}
        />
      )}

      {/* Subscription dialog */}
      {payMode === 'subscribe' && (
        <SubscribeDialog
          selection={selection}
          onClose={() => setSelection(null)}
          onComplete={completed}
        />
      )}
    </div>
  );
};