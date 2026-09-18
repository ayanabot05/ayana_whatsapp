import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import { api } from "../lib/api";
import { Logo } from "@/components/Logo";

// Handles return after Razorpay payment verification.
// With Razorpay Standard Checkout, the payment is verified inline (the modal
// sends the signature to /payments/razorpay/verify). This page is a fallback
// that polls the order status in case the user navigates here manually or
// the inline verification redirect lands here.
export function PaymentSuccess() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  // Support both Razorpay order_id and legacy session_id param names
  const orderId = params.get("order_id") || params.get("session_id");
  const [state, setState] = useState("checking"); // checking | paid | failed | timeout

  useEffect(() => {
    if (!orderId) { setState("paid"); return; } // If no order_id, assume inline verification succeeded
    let attempts = 0;
    let timer;
    const poll = async () => {
      attempts += 1;
      try {
        const { data } = await api.get(`/payments/status/${orderId}`);
        if (data.payment_status === "paid") { setState("paid"); return; }
        if (["failed", "expired"].includes(data.payment_status)) { setState("failed"); return; }
      } catch (_) { /* keep polling */ }
      if (attempts >= 8) { setState("timeout"); return; }
      timer = setTimeout(poll, 2000);
    };
    poll();
    return () => clearTimeout(timer);
  }, [orderId]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-warm-cream px-6 text-center" data-testid="payment-return">
      <Logo size={40} showWord={false} />
      {state === "checking" && (
        <div className="mt-6" data-testid="payment-checking">
          <Loader2 className="w-8 h-8 animate-spin text-ayana-primary mx-auto" />
          <p className="mt-3 text-ayana-secondary">Confirming your payment…</p>
        </div>
      )}
      {state === "paid" && (
        <div className="mt-6" data-testid="payment-paid">
          <CheckCircle2 className="w-12 h-12 text-green-500 mx-auto" />
          <h1 className="mt-4 font-display text-2xl font-semibold text-ayana-text">Payment successful 🎉</h1>
          <p className="mt-2 text-ayana-secondary">Your plan is now active.</p>
          <button onClick={() => navigate("/dashboard")} data-testid="payment-go-dashboard"
            className="mt-6 px-7 py-3 rounded-full bg-ayana-primary text-white font-medium">Go to dashboard</button>
        </div>
      )}
      {(state === "failed" || state === "timeout") && (
        <div className="mt-6" data-testid="payment-failed">
          <XCircle className="w-12 h-12 text-red-400 mx-auto" />
          <h1 className="mt-4 font-display text-2xl font-semibold text-ayana-text">
            {state === "timeout" ? "Still processing" : "Payment not completed"}
          </h1>
          <p className="mt-2 text-ayana-secondary">
            {state === "timeout"
              ? "This is taking longer than usual. Your dashboard will update once confirmed."
              : "We couldn't confirm your payment. You can try again from the dashboard."}
          </p>
          <button onClick={() => navigate("/dashboard")} className="mt-6 px-7 py-3 rounded-full border border-ayana-line text-ayana-text">Back to dashboard</button>
        </div>
      )}
    </div>
  );
}

export function PaymentCancel() {
  const navigate = useNavigate();
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-warm-cream px-6 text-center" data-testid="payment-cancel">
      <Logo size={40} showWord={false} />
      <XCircle className="w-12 h-12 text-ayana-muted mx-auto mt-6" />
      <h1 className="mt-4 font-display text-2xl font-semibold text-ayana-text">Checkout cancelled</h1>
      <p className="mt-2 text-ayana-secondary">No charge was made. You can pick a plan whenever you're ready.</p>
      <button onClick={() => navigate("/dashboard")} className="mt-6 px-7 py-3 rounded-full bg-ayana-primary text-white font-medium">Back to dashboard</button>
    </div>
  );
}