import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api, formatAxiosError } from '@/lib/api';
import { Button } from '@/components/ui/button';

export const BillingStatus = () => {
  const client = useQueryClient();
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(null);
  const { data: access } = useQuery({ queryKey: ['billing-access'], queryFn: () => api.get('/payment/access').then(r => r.data), refetchInterval: 60000 });
  const { data: orders = [] } = useQuery({ queryKey: ['billing-orders'], queryFn: () => api.get('/payment/orders').then(r => r.data) });
  const check = async (id) => {
    setChecking(id); setError('');
    try { await api.post(`/payment/orders/${id}/recheck`); await Promise.all([client.invalidateQueries({ queryKey: ['billing-orders'] }), client.invalidateQueries({ queryKey: ['billing-access'] }), client.invalidateQueries({ queryKey: ['dashboard'] })]); }
    catch (e) { setError(formatAxiosError(e)); } finally { setChecking(null); }
  };
  return <section className="bg-white border border-ayana-line rounded-2xl p-5 space-y-4" data-testid="billing-status-panel"><h2 className="font-display text-lg" data-testid="billing-status-title">Access & payments</h2>
    {access && <div className="text-sm space-y-1" data-testid="billing-entitlement"><p data-testid="billing-access-kind">{access.lifetime ? 'Lifetime sponsored access — no payment or renewal' : `Access: ${access.status.replace(/_/g, ' ')}`}</p>{access.expires_at && <p data-testid="billing-access-expiry">{access.status === 'trial' ? 'Trial ends' : 'Access through'}: {new Date(access.expires_at).toLocaleString()}</p>}<p className="text-ayana-secondary" data-testid="billing-renewal-policy">Prepaid plans renew manually. There are no automatic charges.</p></div>}
    {error && <p role="alert" className="text-red-700 text-sm" data-testid="billing-recheck-error">{error}</p>}
    {orders.length > 0 && <div className="space-y-3" data-testid="billing-order-list">{orders.map(order => <div key={order.id} className="border-t pt-3 flex flex-wrap justify-between gap-3 text-sm" data-testid={`billing-order-${order.id}`}><div><p>{order.plan} · {order.billing === 'year' ? 'annual' : 'monthly'} · {new Intl.NumberFormat(undefined, { style: 'currency', currency: order.currency }).format(order.amount / 100)}</p><p className="text-ayana-secondary" data-testid={`billing-order-status-${order.id}`}>{order.status.replace(/_/g, ' ')}{order.is_test ? ' · TEST transaction' : ''}</p></div>{!['sponsored', 'refunded'].includes(order.status) && <Button variant="outline" size="sm" disabled={!!checking} onClick={() => check(order.id)} data-testid={`billing-check-${order.id}`}>{checking === order.id ? 'Checking…' : 'Check status'}</Button>}</div>)}</div>}
  </section>;
};