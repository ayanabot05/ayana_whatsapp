import { useEffect, useRef, useState, useMemo } from 'react';
import { Loader2, ShieldCheck, Ticket, Calendar, CheckCircle2 } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { api, formatAxiosError } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { checkoutKey, loadCheckout, openCheckout, openSubscriptionModal } from './razorpayCheckout';

const money = (amount, currency) => {
  const code = (currency || 'INR').toUpperCase();
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency: code }).format((amount || 0) / 100);
  } catch {
    return `${code} ${((amount || 0) / 100).toFixed(2)}`;
  }
};

export const CheckoutDialog = ({ selection, onClose, onComplete, allowTrial = false }) => {
  const { user } = useAuth();
  const [config, setConfig] = useState(null);
  const [code, setCode] = useState('');
  const [quote, setQuote] = useState(null);
  const [busy, setBusy] = useState(false);
  const [hosted, setHosted] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [localOrder, setLocalOrder] = useState(null);
  const sequence = useRef(0);

  // Currency is chosen once, on the pricing cards. No second dropdown here.
  const currency = selection?.currency;

  const trialEndDate = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() + 7);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  }, []);

  // Config is only needed for the checkout script and the enabled-currency check.
  useEffect(() => {
    api.get('/payment/config')
      .then(({ data }) => setConfig(data))
      .catch(e => setError(formatAxiosError(e)));
  }, []);

  // Quote only after config has loaded, so we never fire a request before we know what is enabled.
  useEffect(() => {
    if (!selection || !currency || !config) return;
    setCode(''); setError(''); setStatus(''); setLocalOrder(null);
    const current = ++sequence.current; setQuote(null);

    const enabled = config?.currencies?.length ? config.currencies : ['INR', 'USD', 'GBP', 'EUR', 'AED', 'SGD', 'AUD', 'CAD'];
    if (Array.isArray(enabled) && !enabled.includes(currency)) {
      setError(`${currency} checkout is not enabled right now. Please go back and choose another currency.`);
      return;
    }

    api.post('/payment/quote', { ...selection, currency, coupon_code: '' })
      .then(({ data }) => { if (current === sequence.current) setQuote(data); })
      .catch(e => { if (current === sequence.current) setError(formatAxiosError(e)); });
    return () => { sequence.current = current + 1; };
  }, [selection, currency, config]);

  const applyCode = async () => {
    const current = ++sequence.current; setBusy(true); setError(''); setQuote(null);
    try {
      const { data } = await api.post('/payment/quote', { ...selection, currency, coupon_code: code.trim() });
      if (sequence.current === current) setQuote(data);
    } catch (e) {
      setError(formatAxiosError(e));
    } finally {
      setBusy(false);
    }
  };

  const complete = async (result) => {
    if (!result) return;
    if (['paid', 'sponsored', 'authenticated', 'active'].includes(result.status)) {
      try { sessionStorage?.removeItem?.(`ayana-checkout-${user?.id}`); } catch { /* ignore */ }
      const msg = result.status === 'sponsored'
        ? 'Lifetime Raksha access enabled. No payment was taken.'
        : allowTrial && result.status === 'authenticated'
        ? '7-day free trial activated! Care auto-renews after 7 days.'
        : 'Payment captured and verified. Your access is updated.';
      setStatus(msg);
      await onComplete?.(result);
    } else {
      setStatus(
        result.status === 'dismissed'
          ? 'Checkout closed. No card details or payment confirmed.'
          : result.message || 'Payment confirmation is pending. Please check status; do not pay again.'
      );
    }
  };

  // Pay-once order execution (e.g. lifetime coupon activation or legacy prepaid)
  const pay = async () => {
    setBusy(true); setError(''); setStatus('');
    try {
      const details = { ...selection, currency, coupon_code: code.trim() };
      const { data: order } = await api.post('/create-order', { ...details, idempotency_key: checkoutKey(user.id, details) });
      setLocalOrder(order.local_order_id);
      if (order.status === 'sponsored' || order.status === 'paid') {
        await complete(order);
        return;
      }
      if (!order.order_id || order.status !== 'created') {
        setStatus(order.detail || 'This order is awaiting review. Do not create another payment.');
        return;
      }
      await loadCheckout(config?.checkout_script || 'https://checkout.razorpay.com/v1/checkout.js');
      setHosted(true);
      await complete(await openCheckout(order, user, config));
    } catch (e) {
      setError(formatAxiosError(e));
    } finally {
      setHosted(false);
      setBusy(false);
    }
  };

  // Start 7-day trial with card details & auto-renewal via Razorpay Subscriptions
  const startTrialAndSubscribe = async () => {
    setBusy(true); setError(''); setStatus('');
    try {
      if (quote?.lifetime) {
        await pay();
        return;
      }
      const details = {
        plan: selection.plan,
        billing: selection.billing,
        currency,
        coupon_code: code.trim(),
        trial: true,
      };
      const { data: sub } = await api.post('/subscribe', details);
      if (sub?.international_trial) {
        await complete(sub);
        return;
      }
      await loadCheckout(config?.checkout_script || 'https://checkout.razorpay.com/v1/checkout.js');
      setHosted(true);
      const result = await openSubscriptionModal(sub, user, config);
      await complete(result);
    } catch (e) {
      setError(formatAxiosError(e));
    } finally {
      setHosted(false);
      setBusy(false);
    }
  };

  const startInternationalDodoCheckout = async () => {
    setBusy(true); setError(''); setStatus('');
    try {
      const returnUrl = `${window.location.origin}${window.location.pathname}?tab=plan&dodo_session_id={CHECKOUT_SESSION_ID}&plan=${selection?.plan}`;
      const { data } = await api.post('/payment/dodo/checkout', {
        plan: selection?.plan,
        billing: selection?.billing || 'month',
        return_url: returnUrl,
      });
      if (data?.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        throw new Error('Could not initialize international payment session.');
      }
    } catch (e) {
      setError(formatAxiosError(e));
      setBusy(false);
    }
  };

  const recheck = async () => {
    setBusy(true); setError('');
    try {
      const { data } = await api.post(`/payment/orders/${localOrder}/recheck`);
      await complete(data);
    } catch (e) {
      setError(formatAxiosError(e));
    } finally {
      setBusy(false);
    }
  };

  const isTrialMode = allowTrial && !quote?.lifetime;

  return (
    <Dialog open={!!selection && !hosted} onOpenChange={value => { if (!value && !busy) onClose(); }}>
      <DialogContent data-testid="checkout-dialog" className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle data-testid="checkout-title">
            {quote?.plan_name ? `${quote.plan_name} — 7-Day Free Trial` : 'Review your plan'}
          </DialogTitle>
          <DialogDescription data-testid="checkout-description">
            {isTrialMode
              ? `7 days of care for free. Renews automatically at ${money(quote?.amount, currency)}/${selection?.billing === 'year' ? 'year' : 'month'}. Cancel anytime.`
              : `${selection?.billing === 'year' ? '12 months of care.' : 'One month of care.'} Auto-renews unless cancelled.`}
          </DialogDescription>
        </DialogHeader>

        <p className="text-sm text-ayana-secondary" data-testid="checkout-currency">
          Charged in <span className="font-medium text-ayana-text">{currency}</span>
        </p>

        <section className="rounded-xl border border-ayana-line p-4 space-y-3" data-testid="checkout-coupon-section">
          <label htmlFor="checkout-coupon" className="flex gap-2 items-center text-sm font-medium">
            <Ticket className="w-4 h-4" />Have a coupon or free-access code?
          </label>
          <div className="flex gap-2">
            <Input
              id="checkout-coupon"
              data-testid="checkout-coupon-input"
              value={code}
              disabled={busy}
              placeholder="Enter your code"
              onChange={e => { setCode(e.target.value); setQuote(null); sequence.current++; }}
            />
            <Button
              type="button"
              variant="outline"
              disabled={busy || !currency || !config}
              onClick={applyCode}
              data-testid="checkout-apply-coupon"
            >
              Apply
            </Button>
          </div>
          <p className="text-xs text-ayana-secondary" data-testid="checkout-coupon-help">
            Free codes unlock Raksha and must match your verified email. 25% codes apply once to an annual purchase.
          </p>
        </section>

        {quote && (
          <div className="space-y-3 text-sm" data-testid="checkout-quote">
            <div className="flex justify-between">
              <span>Plan price ({selection?.billing === 'year' ? 'Annual' : 'Monthly'})</span>
              <span data-testid="checkout-subtotal">{money(quote.subtotal, currency)}</span>
            </div>

            {quote.discount > 0 && (
              <div className="flex justify-between text-green-700">
                <span>Coupon discount</span>
                <span data-testid="checkout-discount">−{money(quote.discount, currency)}</span>
              </div>
            )}

            {quote.credit > 0 && (
              <div className="flex justify-between text-ayana-primary" data-testid="checkout-credit">
                <span>Credit for remaining time on your plan</span>
                <span>−{money(quote.credit, currency)}</span>
              </div>
            )}

            {isTrialMode && (
              <div className="flex justify-between text-emerald-700 font-medium">
                <span className="flex items-center gap-1.5">
                  <CheckCircle2 className="w-4 h-4" /> 7-day free trial discount
                </span>
                <span>−{money(quote.amount, currency)}</span>
              </div>
            )}

            <div className="flex justify-between border-t pt-3 font-semibold text-lg">
              <span>Total today</span>
              <span data-testid="checkout-total">{money(isTrialMode ? 0 : quote.amount, currency)}</span>
            </div>

            {isTrialMode ? (
              <div className="rounded-xl bg-emerald-50/70 border border-emerald-200/80 p-3.5 space-y-1.5 text-xs text-emerald-950">
                <p className="font-semibold flex items-center gap-1.5 text-emerald-900">
                  <Calendar className="w-3.5 h-3.5" />
                  First auto-deduction: {trialEndDate}
                </p>
                <p className="text-emerald-800/90 leading-relaxed">
                  {currency !== 'INR' && config?.dodo_enabled
                    ? `Dodo Payments securely verifies your international card to activate your 7-day free trial. ${money(0, currency)} is charged today. After 7 days, your subscription automatically renews at ${money(quote.amount, currency)}/${selection?.billing === 'year' ? 'year' : 'month'}.`
                    : `Razorpay securely verifies your card to activate your 7-day free trial. ${money(0, currency)} is deducted today. After 7 days, your subscription automatically renews at ${money(quote.amount, currency)}/${selection?.billing === 'year' ? 'year' : 'month'}.`}
                </p>
                <p className="text-emerald-700/80">
                  You can cancel anytime before {trialEndDate} from your dashboard with one click — zero penalty.
                </p>
              </div>
            ) : (
              <p className="text-xs text-ayana-secondary" data-testid="checkout-terms">{quote.terms}</p>
            )}
          </div>
        )}

        {error && <p role="alert" data-testid="checkout-error" className="text-sm text-red-700">{error}</p>}
        {status && <p role="status" data-testid="checkout-status" className="text-sm rounded-xl bg-ayana-bg p-3">{status}</p>}

        <Button
          disabled={busy || !quote}
          onClick={
            currency !== 'INR' && config?.dodo_enabled
              ? startInternationalDodoCheckout
              : (isTrialMode ? startTrialAndSubscribe : pay)
          }
          data-testid="checkout-pay-button"
          className="w-full h-11 text-base font-medium shadow-md"
        >
          {busy ? (
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
          ) : (
            <ShieldCheck className="w-4 h-4 mr-2" />
          )}
          {quote?.lifetime
            ? 'Activate lifetime access — free'
            : currency !== 'INR' && config?.dodo_enabled
            ? (isTrialMode ? 'Start 7-Day Free Trial (Card / Apple Pay)' : 'Pay with International Card (Dodo)')
            : isTrialMode
            ? 'Start 7-day free trial with Razorpay'
            : 'Pay securely with Razorpay'}
        </Button>

        {localOrder && (
          <Button variant="outline" disabled={busy} onClick={recheck} data-testid="checkout-recheck">
            Check payment status
          </Button>
        )}

        <Button variant="ghost" disabled={busy} onClick={onClose} data-testid="checkout-cancel">
          Back
        </Button>
      </DialogContent>
    </Dialog>
  );
};