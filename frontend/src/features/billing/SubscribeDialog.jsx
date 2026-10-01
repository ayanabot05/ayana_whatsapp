// SubscribeDialog — Razorpay Subscription modal.
// Opens the Razorpay checkout in subscription mode (subscription_id instead of order_id).
// On mandate authorisation, calls /verify-subscription to activate.
import { useEffect, useRef, useState } from 'react';
import { Loader2, RefreshCw } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { api, formatAxiosError } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { loadCheckout, openSubscriptionModal } from './razorpayCheckout';

const money = (amount, currency) => {
  const code = (currency || 'INR').toUpperCase();
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency: code }).format((amount || 0) / 100);
  } catch {
    return `₹${((amount || 0) / 100).toFixed(2)}`;
  }
};

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
