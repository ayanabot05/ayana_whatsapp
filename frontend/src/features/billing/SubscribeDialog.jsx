// SubscribeDialog — Razorpay Subscription modal.
// Opens the Razorpay checkout in subscription mode (subscription_id instead of order_id).
// On mandate authorisation, calls /verify-subscription to activate.
import { useEffect, useRef, useState } from 'react';
import { Loader2, RefreshCw } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { api, formatAxiosError } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { loadCheckout } from './razorpayCheckout';

const money = (amount, currency) =>
  new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount / 100);

const openSubscriptionModal = (sub, user, config) =>
  new Promise((resolve, reject) => {
    let settled = false;
    const finish = (fn, val) => { if (!settled) { settled = true; fn(val); } };
    const modal = new window.Razorpay({
      key: sub.key_id,
      subscription_id: sub.subscription_id,
      name: 'AYANA',
      description: `${sub.plan} — ${sub.billing === 'year' ? 'annual subscription, renews each year' : 'monthly subscription, renews each month'}`,
      prefill: { name: user?.name, email: user?.email, contact: user?.phone },
      theme: { color: '#0f3d2e' },
      retry: { enabled: false },
      handler: async (result) => {
        if (settled) return;
        settled = true;
        try {
          const { data } = await api.post('/verify-subscription', result);
          resolve(data);
        } catch (err) {
          reject(err);
        }
      },
      modal: {
        confirm_close: true,
        ondismiss: () => finish(resolve, { status: 'dismissed' }),
      },
    });
    modal.on('payment.failed', (ev) => {
      finish(reject, new Error(ev.error?.description || 'The subscription authorisation failed.'));
      modal.close();
    });
    modal.open();
  });

export const SubscribeDialog = ({ selection, onClose, onComplete }) => {
  const { user } = useAuth();
  const [config, setConfig] = useState(null);
  const [busy, setBusy] = useState(false);
  const [hosted, setHosted] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [preview, setPreview] = useState(null);
  const seqRef = useRef(0);

  // Load payment config once
  useEffect(() => {
    api.get('/payment/config')
      .then(({ data }) => setConfig(data))
      .catch(e => setError(formatAxiosError(e)));
  }, []);

  // Show a live price preview whenever selection changes
  useEffect(() => {
    if (!selection || !config) return;
    setPreview(null); setError(''); setStatus('');
    const seq = ++seqRef.current;
    api.post('/payment/quote', { ...selection, coupon_code: '' })
      .then(({ data }) => { if (seqRef.current === seq) setPreview(data); })
      .catch(e => { if (seqRef.current === seq) setError(formatAxiosError(e)); });
  }, [selection, config]);

  const subscribe = async () => {
    setBusy(true); setError(''); setStatus('');
    try {
      const { data: sub } = await api.post('/subscribe', { ...selection, coupon_code: '' });
      await loadCheckout(config.checkout_script);
      setHosted(true);
      const result = await openSubscriptionModal(sub, user, config);
      if (['authenticated', 'active'].includes(result.status)) {
        sessionStorage.removeItem(`ayana-checkout-${user?.id}`);
        setStatus('Subscription activated! Care auto-renews each period. Cancel anytime from your dashboard.');
        await onComplete?.(result);
      } else if (result.status === 'dismissed') {
        setStatus('Subscription not confirmed. No charge has been made.');
      } else {
        setStatus(result.message || `Subscription status: ${result.status}.`);
      }
    } catch (e) {
      setError(formatAxiosError(e));
    } finally {
      setHosted(false); setBusy(false);
    }
  };

  const billingLabel = selection?.billing === 'year'
    ? 'Charged once a year — renews automatically.'
    : 'Charged once a month — renews automatically.';

  return (
    <Dialog open={!!selection && !hosted} onOpenChange={v => { if (!v && !busy) onClose(); }}>
      <DialogContent data-testid="subscribe-dialog" className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle data-testid="subscribe-title">
            <RefreshCw className="inline w-4 h-4 mr-2 text-ayana-primary" />
            Subscribe — {preview?.plan_name || selection?.plan}
          </DialogTitle>
          <DialogDescription data-testid="subscribe-description">
            {billingLabel} Cancel anytime; no penalties.
          </DialogDescription>
        </DialogHeader>

        {config?.test_mode && (
          <p className="rounded-xl bg-amber-50 border border-amber-200 p-3 text-sm text-amber-900" data-testid="subscribe-test-mode">
            Razorpay test mode. No real money will be charged.
          </p>
        )}

        {preview && (
          <div className="space-y-2 text-sm" data-testid="subscribe-preview">
            <div className="flex justify-between">
              <span>{selection?.billing === 'year' ? 'Annual price' : 'Monthly price'}</span>
              <span data-testid="subscribe-amount">{money(preview.subtotal, selection?.currency)}</span>
            </div>
            <div className="flex justify-between border-t pt-3 font-semibold text-lg">
              <span>Charged today</span>
              <span>{money(preview.subtotal, selection?.currency)}</span>
            </div>
            <p className="text-xs text-ayana-secondary">
              {billingLabel} You can cancel at any time from the Plan tab — access continues until the end of the paid period.
            </p>
          </div>
        )}

        {error && <p role="alert" data-testid="subscribe-error" className="text-sm text-red-700">{error}</p>}
        {status && <p role="status" data-testid="subscribe-status" className="text-sm rounded-xl bg-ayana-bg p-3">{status}</p>}

        <Button
          disabled={busy || !preview}
          onClick={subscribe}
          data-testid="subscribe-pay-button"
          className="w-full"
        >
          {busy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
          Subscribe with Razorpay
        </Button>
        <Button variant="ghost" disabled={busy} onClick={onClose} data-testid="subscribe-cancel">
          Back
        </Button>
      </DialogContent>
    </Dialog>
  );
};
