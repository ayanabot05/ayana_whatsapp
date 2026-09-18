// Only the public key and stored order ID enter the browser. No payment details
// are stored here; Razorpay's hosted modal handles the card/UPI interaction.
import { api } from '@/lib/api';
let scriptPromise;

export const loadCheckout = (src) => {
  if (window.Razorpay) return Promise.resolve();
  if (!scriptPromise) scriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    const timeout = setTimeout(() => fail(), 15000);
    const fail = () => { clearTimeout(timeout); script.remove(); scriptPromise = null; reject(new Error('Razorpay could not load. Check your connection and try again.')); };
    script.src = src; script.async = true;
    script.onload = () => { clearTimeout(timeout); window.Razorpay ? resolve() : fail(); };
    script.onerror = fail;
    document.head.appendChild(script);
  });
  return scriptPromise;
};

export const openCheckout = (order, user, config) => new Promise((resolve, reject) => {
  let settled = false;
  const finish = (fn, value) => { if (!settled) { settled = true; fn(value); } };
  const modal = new window.Razorpay({
    key: order.key_id, order_id: order.order_id, amount: order.amount, currency: order.currency,
    name: 'AYANA', description: `${order.plan} — ${order.billing === 'year' ? '12 months' : '1 month'} prepaid`,
    prefill: { name: user.name, email: user.email, contact: user.phone },
    theme: { color: '#0f3d2e' }, retry: { enabled: false },
    handler: async (result) => {
      if (settled) return;
      settled = true; // onDismiss must not race the server verification request.
      try { const { data } = await api.post('/verify-payment', result); resolve(data); }
      catch (error) { reject(error); }
    },
    modal: { confirm_close: true, ondismiss: () => finish(resolve, { status: 'dismissed' }) },
  });
  modal.on('payment.failed', event => {
    const error = new Error(event.error?.description || 'The payment failed. No paid access has been granted.');
    finish(reject, error); modal.close();
  });
  modal.open();
});

export const checkoutKey = (userId, details) => {
  const storageKey = `ayana-checkout-${userId}`;
  let saved;
  try { saved = JSON.parse(sessionStorage.getItem(storageKey)); } catch { /* corrupt local cache */ }
  const selection = JSON.stringify(details);
  if (saved?.selection === selection) return saved.id;
  const id = crypto.randomUUID();
  sessionStorage.setItem(storageKey, JSON.stringify({ selection, id }));
  return id;
};