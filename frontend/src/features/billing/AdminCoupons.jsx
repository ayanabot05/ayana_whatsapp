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
  const isLifetime = coupon.kind === 'lifetime';

  const save = async () => {
    setBusy(true); setError('');
    try { await api.patch(`/admin/coupons/${coupon.id}`, { email: email || null, active }); await onSaved(); }
    catch (e) { setError(formatAxiosError(e)); } finally { setBusy(false); }
  };

  return (
    <article className="rounded-2xl border border-ayana-line p-5 space-y-3 bg-white" data-testid={`admin-coupon-${coupon.id}`}>
      <div className="flex justify-between flex-wrap gap-2">
        <h3 className="font-semibold" data-testid={`coupon-label-${coupon.id}`}>{coupon.label}</h3>
        <span className="text-sm text-ayana-secondary" data-testid={`coupon-kind-${coupon.id}`}>
          {isLifetime ? 'Lifetime Raksha gift' : `${coupon.percent}% off annual`} · {coupon.code_hint}
        </span>
      </div>

      {isLifetime ? (
        <div className="flex flex-wrap gap-3 items-center">
          <Input
            type="email" disabled={locked || busy} value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="Recipient email (required for gifts)"
            aria-label={`Recipient for ${coupon.label}`}
            data-testid={`coupon-email-${coupon.id}`}
            className="flex-1 min-w-[200px]"
          />
          <label className="text-sm flex gap-2 items-center">
            <input type="checkbox" checked={active} disabled={locked || busy} onChange={e => setActive(e.target.checked)} data-testid={`coupon-active-${coupon.id}`} />
            Active
          </label>
          <Button disabled={locked || busy} onClick={save} data-testid={`coupon-save-${coupon.id}`}>
            {busy ? 'Saving…' : 'Save assignment'}
          </Button>
        </div>
      ) : (
        <div className="text-sm text-ayana-secondary space-y-1" data-testid={`coupon-usage-${coupon.id}`}>
          <p>Used {coupon.redeemed_count} / {coupon.max_redemptions}</p>
          <p>{coupon.expires_at ? `Expires ${new Date(coupon.expires_at).toLocaleDateString()}` : 'No expiry'}</p>
          <p>{coupon.active ? 'Active' : 'Inactive'}</p>
        </div>
      )}

      <p className="text-xs text-ayana-secondary" data-testid={`coupon-state-${coupon.id}`}>
        {isLifetime
          ? (coupon.redeemed_at ? 'Redeemed once; cannot be reassigned.' : coupon.reserved_by ? 'Reserved to a checkout; cannot be reassigned.' : 'Single-account use. Full codes are delivered privately, not listed here.')
          : 'Multi-use code. The plaintext code was shown once at creation and cannot be recovered — reissue a new coupon if it was lost.'}
      </p>
      {error && <p role="alert" className="text-sm text-red-700" data-testid={`coupon-error-${coupon.id}`}>{error}</p>}
    </article>
  );
};

const CreateCouponForm = ({ onCreated }) => {
  const [label, setLabel] = useState('');
  const [percent, setPercent] = useState(25);
  const [days, setDays] = useState(30);
  const [limit, setLimit] = useState(10);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true); setError(''); setResult(null);
    try {
      const { data } = await api.post('/admin/coupons', {
        label,
        percent: Number(percent),
        days_valid: Number(days) || null,
        max_redemptions: Number(limit),
      });
      setResult(data);
      setLabel('');
      onCreated?.();
    } catch (e) { setError(formatAxiosError(e)); } finally { setBusy(false); }
  };

  return (
    <div className="rounded-2xl border border-ayana-line p-5 space-y-3 bg-white" data-testid="admin-create-coupon">
      <h3 className="font-semibold">Create a coupon</h3>
      <Input
        placeholder="Label (e.g. Diwali offer)"
        value={label} onChange={e => setLabel(e.target.value)}
        data-testid="create-coupon-label"
      />
      <div className="flex gap-3 flex-wrap">
        <label className="text-sm flex-1 min-w-[100px]">
          % off
          <Input type="number" min="1" max="100" value={percent} onChange={e => setPercent(e.target.value)} data-testid="create-coupon-percent" />
        </label>
        <label className="text-sm flex-1 min-w-[100px]">
          Days valid
          <Input type="number" min="0" value={days} onChange={e => setDays(e.target.value)} data-testid="create-coupon-days" />
        </label>
        <label className="text-sm flex-1 min-w-[100px]">
          User limit
          <Input type="number" min="1" value={limit} onChange={e => setLimit(e.target.value)} data-testid="create-coupon-limit" />
        </label>
      </div>
      <Button disabled={busy || !label} onClick={create} data-testid="create-coupon-submit">
        {busy ? 'Creating…' : 'Create coupon'}
      </Button>
      {error && <p role="alert" className="text-sm text-red-700" data-testid="create-coupon-error">{error}</p>}
      {result && (
        <p className="text-sm bg-green-50 border border-green-200 rounded-xl p-3" data-testid="create-coupon-result">
          Code: <b>{result.code}</b> — {result.percent}% off, {result.max_redemptions} user{result.max_redemptions === 1 ? '' : 's'}
          {result.expires_at ? `, expires ${new Date(result.expires_at).toLocaleDateString()}` : ', no expiry'}.
          <br />Copy this now — it won't be shown again.
        </p>
      )}
    </div>
  );
};

export const AdminCoupons = () => {
  const client = useQueryClient();
  const { data = [], isLoading, error } = useQuery({ queryKey: ['admin-coupons'], queryFn: () => api.get('/admin/coupons').then(r => r.data) });
  const invalidate = () => client.invalidateQueries({ queryKey: ['admin-coupons'] });

  return (
    <section className="space-y-4" data-testid="admin-coupons-section">
      <h2 className="font-display text-lg" data-testid="admin-coupons-title">Coupons</h2>
      <p className="text-sm text-ayana-secondary" data-testid="admin-coupons-help">
        Assign the founder & friends lifetime gifts to specific emails below, or create a new multi-use percent-off coupon with its own expiry and user limit.
      </p>
      <CreateCouponForm onCreated={invalidate} />
      {isLoading && <p data-testid="coupons-loading">Loading coupons…</p>}
      {error && <p role="alert" data-testid="coupons-load-error">{formatAxiosError(error)}</p>}
      {data.map(c => <CouponRow key={c.id} coupon={c} onSaved={invalidate} />)}
    </section>
  );
};