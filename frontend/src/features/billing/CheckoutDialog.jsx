import { useEffect, useRef, useState } from 'react';
import { Loader2, ShieldCheck, Ticket } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { api, formatAxiosError } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { checkoutKey, loadCheckout, openCheckout } from './razorpayCheckout';

const money = (amount, currency) => new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount / 100);

export const CheckoutDialog = ({ selection, onClose, onComplete, allowTrial = false }) => {
  const { user } = useAuth();
  const [config, setConfig] = useState(null);
  const [currency, setCurrency] = useState('');
  const [code, setCode] = useState('');
  const [quote, setQuote] = useState(null);
  const [busy, setBusy] = useState(false);
  const [hosted, setHosted] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [localOrder, setLocalOrder] = useState(null);
  const sequence = useRef(0);
  useEffect(() => { api.get('/payment/config').then(({ data }) => { setConfig(data); setCurrency(data.currencies[0] || ''); }).catch(e => setError(formatAxiosError(e))); }, []);
  useEffect(() => {
    if (!selection || !currency) return;
    setCode(''); setError(''); setStatus(''); setLocalOrder(null);
    const current = ++sequence.current; setQuote(null);
    api.post('/payment/quote', { ...selection, currency, coupon_code: '' }).then(({ data }) => { if (current === sequence.current) setQuote(data); }).catch(e => { if (current === sequence.current) setError(formatAxiosError(e)); });
    return () => { sequence.current++; };
  }, [selection, currency]);
  const applyCode = async () => {
    const current = ++sequence.current; setBusy(true); setError(''); setQuote(null);
    try { const { data } = await api.post('/payment/quote', { ...selection, currency, coupon_code: code.trim() }); if (sequence.current === current) setQuote(data); }
    catch (e) { setError(formatAxiosError(e)); }
    finally { setBusy(false); }
  };
  const complete = async (result) => {
    if (['paid', 'sponsored'].includes(result.status)) {
      sessionStorage.removeItem(`ayana-checkout-${user.id}`);
      setStatus(result.status === 'sponsored' ? 'Lifetime Raksha access enabled. No payment was taken.' : 'Payment captured and verified. Your access is updated.');
      await onComplete?.(result);
    } else setStatus(result.status === 'dismissed' ? 'Checkout closed. No payment has been confirmed. Check status before paying again.' : result.message || 'Payment confirmation is pending. Please check status; do not pay again.');
  };
  const pay = async () => {
    setBusy(true); setError(''); setStatus('');
    try {
      const details = { ...selection, currency, coupon_code: code.trim() };
      const { data: order } = await api.post('/create-order', { ...details, idempotency_key: checkoutKey(user.id, details) });
      setLocalOrder(order.local_order_id);
      if (order.status === 'sponsored') { await complete(order); return; }
      if (order.status === 'paid') { await complete(order); return; }
      if (!order.order_id || order.status !== 'created') { setStatus(order.detail || 'This order is awaiting review. Do not create another payment.'); return; }
      await loadCheckout(config.checkout_script);
      setHosted(true);
      await complete(await openCheckout(order, user, config));
    } catch (e) { setError(formatAxiosError(e)); }
    finally { setHosted(false); setBusy(false); }
  };
  const recheck = async () => {
    setBusy(true); setError('');
    try { const { data } = await api.post(`/payment/orders/${localOrder}/recheck`); await complete(data); }
    catch (e) { setError(formatAxiosError(e)); } finally { setBusy(false); }
  };
  const trial = async () => {
    setBusy(true); setError('');
    try { await api.post('/payment/trial', { ...selection, currency, coupon_code: '' }); await onComplete?.({ status: 'trial' }); }
    catch (e) { setError(formatAxiosError(e)); } finally { setBusy(false); }
  };
  return <Dialog open={!!selection && !hosted} onOpenChange={value => { if (!value && !busy) onClose(); }}><DialogContent data-testid="checkout-dialog" className="max-w-lg max-h-[90vh] overflow-y-auto">
    <DialogHeader><DialogTitle data-testid="checkout-title">{quote?.plan_name || 'Review your plan'}</DialogTitle><DialogDescription data-testid="checkout-description">{selection?.billing === 'year' ? '12 months of care, paid once.' : 'One month of care, paid once.'} No automatic renewal.</DialogDescription></DialogHeader>
    {config?.test_mode && <p className="rounded-xl bg-amber-50 border border-amber-200 p-3 text-sm text-amber-900" data-testid="checkout-test-mode">Razorpay test mode. No real money will be charged.</p>}
    <label className="text-sm font-medium" htmlFor="checkout-currency">Currency charged</label><select id="checkout-currency" value={currency} disabled={busy} onChange={e => setCurrency(e.target.value)} data-testid="checkout-currency" className="border rounded-xl p-3 bg-white">{config?.currencies.map(c => <option key={c} value={c}>{c}</option>)}</select>
    <section className="rounded-xl border border-ayana-line p-4 space-y-3" data-testid="checkout-coupon-section"><label htmlFor="checkout-coupon" className="flex gap-2 items-center text-sm font-medium"><Ticket className="w-4 h-4" />Have a coupon or free-access code?</label><div className="flex gap-2"><Input id="checkout-coupon" data-testid="checkout-coupon-input" value={code} disabled={busy} placeholder="Enter your code" onChange={e => { setCode(e.target.value); setQuote(null); sequence.current++; }} /><Button type="button" variant="outline" disabled={busy || !currency} onClick={applyCode} data-testid="checkout-apply-coupon">Apply</Button></div><p className="text-xs text-ayana-secondary" data-testid="checkout-coupon-help">Free codes unlock Raksha and must match your verified email. 25% codes apply once to an annual purchase.</p></section>
    {quote && <div className="space-y-2 text-sm" data-testid="checkout-quote"><div className="flex justify-between"><span>Plan price</span><span data-testid="checkout-subtotal">{money(quote.subtotal, currency)}</span></div><div className="flex justify-between"><span>Coupon discount</span><span data-testid="checkout-discount">−{money(quote.discount, currency)}</span></div><div className="flex justify-between border-t pt-3 font-semibold text-lg"><span>Total today</span><span data-testid="checkout-total">{money(quote.amount, currency)}</span></div><p className="text-xs text-ayana-secondary" data-testid="checkout-terms">{quote.terms}</p></div>}
    {error && <p role="alert" data-testid="checkout-error" className="text-sm text-red-700">{error}</p>}
    {status && <p role="status" data-testid="checkout-status" className="text-sm rounded-xl bg-ayana-bg p-3">{status}</p>}
    <Button disabled={busy || !quote} onClick={pay} data-testid="checkout-pay-button">{busy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <ShieldCheck className="w-4 h-4 mr-2" />}{quote?.lifetime ? 'Activate lifetime access — free' : 'Pay securely with Razorpay'}</Button>
    {localOrder && <Button variant="outline" disabled={busy} onClick={recheck} data-testid="checkout-recheck">Check payment status</Button>}
    {allowTrial && <Button variant="outline" disabled={busy || !currency} onClick={trial} data-testid="checkout-start-trial">Continue with a 7-day trial — no card</Button>}
    <Button variant="ghost" disabled={busy} onClick={onClose} data-testid="checkout-cancel">Back</Button>
  </DialogContent></Dialog>;
};