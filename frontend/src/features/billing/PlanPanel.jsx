import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Crown, Ticket } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '@/lib/api';
import { PricingCards } from '@/components/PricingCards';
import { Button } from '@/components/ui/button';
import { CheckoutDialog } from './CheckoutDialog';
import { BillingStatus } from './BillingStatus';

export const PlanPanel = ({ plans, currencies, planId, plan, usage, circle, reload }) => {
  const [selection, setSelection] = useState(null);
  const client = useQueryClient();
  const { data: access } = useQuery({ queryKey: ['billing-access'], queryFn: () => api.get('/payment/access').then(r => r.data) });
  const completed = async result => {
    setSelection(null);
    toast.success(result.status === 'sponsored' ? 'Lifetime Raksha access enabled—completely free.' : result.status === 'trial' ? 'Trial plan selected.' : 'Payment captured and verified.');
    await Promise.all([reload(), client.invalidateQueries({ queryKey: ['billing-access'] }), client.invalidateQueries({ queryKey: ['billing-orders'] })]);
  };
  if (circle?.role === 'member') return <p className="rounded-2xl bg-white p-6 border border-ayana-line text-sm" data-testid="billing-owner-only">Only the account owner manages billing. You are covered under {circle.owner?.name}'s {plan?.name} plan.</p>;
  return <div className="space-y-5 max-w-4xl" data-testid="plan-panel"><BillingStatus />
    <section className="bg-white rounded-2xl border border-ayana-line p-5 space-y-3" data-testid="plan-usage"><h2 className="font-display text-lg flex items-center gap-2"><Crown className="w-5 h-5 text-ayana-primary" />Your care plan</h2><p className="text-sm text-ayana-secondary" data-testid="plan-current-limits">{usage.parents ?? 0}/{plan?.limits?.parents ?? '—'} parents · {usage.family_members_used ?? 0}/{plan?.limits?.family_members ?? 0} additional family members</p><p className="text-sm text-ayana-secondary" data-testid="plan-prepaid-policy">Upgrades are prepaid. Renewals and lower-tier purchases do not remove existing paid time. No automatic charges.</p>{!access?.lifetime && <Button variant="outline" onClick={() => setSelection({ plan: 'raksha', billing: 'year' })} data-testid="redeem-lifetime-code"><Ticket className="w-4 h-4 mr-2" />Redeem a free-access code</Button>}</section>
    <section className="bg-white rounded-2xl border border-ayana-line p-5 space-y-4"><h2 className="font-display text-lg" data-testid="plan-purchase-title">{access?.lifetime ? 'Your lifetime plan is covered' : 'Choose, renew, or apply a coupon'}</h2><PricingCards plans={plans} currencies={currencies} selectedPlan={planId} onSelect={access?.lifetime ? undefined : (id, billing) => setSelection({ plan: id, billing })} actionLabel={p => p.id === planId ? 'Renew / apply coupon' : 'Choose plan'} compact /></section>
    <CheckoutDialog selection={selection} onClose={() => setSelection(null)} onComplete={completed} />
  </div>;
};