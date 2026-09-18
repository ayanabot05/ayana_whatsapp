import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api, formatAxiosError } from '@/lib/api';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';

const CouponRow = ({ coupon, onSaved }) => {
  const [email, setEmail] = useState(coupon.allowed_email || '');
  const [active, setActive] = useState(coupon.active);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const locked = !!(coupon.reserved_by || coupon.redeemed_at);
  const save = async () => {
    setBusy(true); setError('');
    try { await api.patch(`/admin/coupons/${coupon.id}`, { email: email || null, active }); await onSaved(); }
    catch (e) { setError(formatAxiosError(e)); } finally { setBusy(false); }
  };
  return <article className="rounded-2xl border border-ayana-line p-5 space-y-3 bg-white" data-testid={`admin-coupon-${coupon.id}`}><div className="flex justify-between flex-wrap gap-2"><h3 className="font-semibold" data-testid={`coupon-label-${coupon.id}`}>{coupon.label}</h3><span className="text-sm text-ayana-secondary" data-testid={`coupon-kind-${coupon.id}`}>{coupon.kind === 'lifetime' ? 'Lifetime Raksha gift' : '25% off first annual purchase'} · {coupon.code_hint}</span></div><div className="flex flex-wrap gap-3 items-center"><Input type="email" disabled={locked || busy} value={email} onChange={e => setEmail(e.target.value)} placeholder="Recipient email (required for gifts)" aria-label={`Recipient for ${coupon.label}`} data-testid={`coupon-email-${coupon.id}`} className="flex-1 min-w-[200px]" /><label className="text-sm flex gap-2 items-center"><input type="checkbox" checked={active} disabled={locked || busy} onChange={e => setActive(e.target.checked)} data-testid={`coupon-active-${coupon.id}`} />Active</label><Button disabled={locked || busy} onClick={save} data-testid={`coupon-save-${coupon.id}`}>{busy ? 'Saving…' : 'Save assignment'}</Button></div><p className="text-xs text-ayana-secondary" data-testid={`coupon-state-${coupon.id}`}>{coupon.redeemed_at ? 'Redeemed once; cannot be reassigned.' : coupon.reserved_by ? 'Reserved to a checkout; cannot be reassigned.' : 'Single-account use. Full codes are delivered privately, not listed here.'}</p>{error && <p role="alert" className="text-sm text-red-700" data-testid={`coupon-error-${coupon.id}`}>{error}</p>}</article>;
};

export const AdminCoupons = () => {
  const client = useQueryClient();
  const { data = [], isLoading, error } = useQuery({ queryKey: ['admin-coupons'], queryFn: () => api.get('/admin/coupons').then(r => r.data) });
  return <section className="space-y-4" data-testid="admin-coupons-section"><h2 className="font-display text-lg" data-testid="admin-coupons-title">Founder & friends coupons</h2><p className="text-sm text-ayana-secondary" data-testid="admin-coupons-help">Assign the three free gifts to your email and exactly two friends. Six other codes each give 25% off one annual purchase. Coupons never replace login.</p>{isLoading && <p data-testid="coupons-loading">Loading coupons…</p>}{error && <p role="alert" data-testid="coupons-load-error">{formatAxiosError(error)}</p>}{data.map(c => <CouponRow key={c.id} coupon={c} onSaved={() => client.invalidateQueries({ queryKey: ['admin-coupons'] })} />)}</section>;
};