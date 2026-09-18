// SubscriptionStatus — shows active subscriptions and cancel-at-period-end option.
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { RefreshCw, XCircle } from 'lucide-react';
import { api, formatAxiosError } from '@/lib/api';
import { Button } from '@/components/ui/button';

const STATUS_LABEL = {
  created: 'Pending authorisation',
  authenticated: 'Authorised — first charge pending',
  active: 'Active',
  halted: 'Payment failed — update your card',
  cancelled: 'Cancelled',
  completed: 'Completed',
  expired: 'Expired',
};

const money = (amount, currency) =>
  new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount / 100);

const SubRow = ({ sub, onSaved }) => {
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');

  const cancelSub = async () => {
    if (!window.confirm('Cancel at end of period? You keep access until then.')) return;
    setCancelling(true); setError(''); setMsg('');
    try {
      const { data } = await api.post(`/subscriptions/${sub.id}/cancel`);
      setMsg(data.message || 'Cancellation scheduled.');
      await onSaved();
    } catch (e) { setError(formatAxiosError(e)); }
    finally { setCancelling(false); }
  };

  const isActive = ['authenticated', 'active'].includes(sub.status);
  const canCancel = isActive && !sub.cancel_at_period_end;

  return (
    <div
      className="border-t pt-3 space-y-1 text-sm"
      data-testid={`sub-row-${sub.id}`}
    >
      <div className="flex flex-wrap justify-between gap-3 items-start">
        <div>
          <p className="font-medium capitalize">
            <RefreshCw className="inline w-3.5 h-3.5 mr-1 text-ayana-primary" />
            {sub.plan} — {sub.billing === 'year' ? 'annual' : 'monthly'} · {money(sub.amount, sub.currency)}
          </p>
          <p className="text-ayana-secondary" data-testid={`sub-status-${sub.id}`}>
            {STATUS_LABEL[sub.status] || sub.status}
            {sub.is_test ? ' · TEST' : ''}
          </p>
          {sub.current_period_end && (
            <p className="text-ayana-secondary text-xs">
              {sub.cancel_at_period_end ? 'Access ends' : 'Next charge'}: {new Date(sub.current_period_end).toLocaleDateString()}
            </p>
          )}
          {sub.cancel_at_period_end && (
            <p className="text-amber-700 text-xs font-medium">Cancellation scheduled — access continues until the date above.</p>
          )}
        </div>
        {canCancel && (
          <Button
            variant="outline"
            size="sm"
            disabled={cancelling}
            onClick={cancelSub}
            data-testid={`sub-cancel-${sub.id}`}
            className="text-red-600 border-red-200 hover:bg-red-50"
          >
            <XCircle className="w-3.5 h-3.5 mr-1" />
            {cancelling ? 'Cancelling…' : 'Cancel at period end'}
          </Button>
        )}
      </div>
      {error && <p role="alert" className="text-red-700 text-xs">{error}</p>}
      {msg && <p role="status" className="text-ayana-secondary text-xs">{msg}</p>}
    </div>
  );
};

export const SubscriptionStatus = () => {
  const client = useQueryClient();
  const { data: subs = [], isLoading } = useQuery({
    queryKey: ['billing-subscriptions'],
    queryFn: () => api.get('/subscriptions').then(r => r.data),
    refetchInterval: 60000,
  });

  const active = subs.filter(s => ['created', 'authenticated', 'active'].includes(s.status));
  if (!isLoading && active.length === 0) return null;

  return (
    <section
      className="bg-white border border-ayana-line rounded-2xl p-5 space-y-4"
      data-testid="subscription-status-panel"
    >
      <h2 className="font-display text-lg flex items-center gap-2">
        <RefreshCw className="w-4 h-4 text-ayana-primary" />
        Your subscriptions
      </h2>
      {isLoading && <p className="text-sm text-ayana-secondary">Loading…</p>}
      {active.map(sub => (
        <SubRow
          key={sub.id}
          sub={sub}
          onSaved={() => client.invalidateQueries({ queryKey: ['billing-subscriptions'] })}
        />
      ))}
    </section>
  );
};
