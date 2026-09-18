/**
 * useRazorpay.js — React hook for Razorpay Standard Web Checkout.
 *
 * Opens the Razorpay modal with the given order details, handles payment
 * success/failure, and sends the signature to the backend for verification.
 */
import { useCallback } from "react";
import { api } from "./api";

const RAZORPAY_KEY_ID = process.env.REACT_APP_RAZORPAY_KEY_ID || "";

/**
 * Returns an `openRazorpayCheckout` function.
 *
 * @param {object} opts
 * @param {function} opts.onSuccess  — called with { plan, billing } after verified payment
 * @param {function} opts.onError    — called with error message string
 * @param {function} opts.onDismiss  — called when user closes the modal without paying
 */
export function useRazorpay({ onSuccess, onError, onDismiss } = {}) {
  const openRazorpayCheckout = useCallback(
    /**
     * @param {object} orderData — response from POST /payment/checkout when skipped=false
     * @param {string} orderData.order_id
     * @param {number} orderData.amount      — in smallest currency unit
     * @param {string} orderData.currency
     * @param {string} orderData.key_id      — Razorpay public key
     * @param {string} orderData.plan_name
     * @param {string} orderData.billing
     * @param {object} [userInfo]            — { name, email, phone } for prefill
     */
    (orderData, userInfo = {}) => {
      if (!window.Razorpay) {
        onError?.("Razorpay checkout script not loaded. Please refresh the page.");
        return;
      }

      const keyId = orderData.key_id || RAZORPAY_KEY_ID;
      if (!keyId) {
        onError?.("Razorpay key not configured.");
        return;
      }

      const options = {
        key: keyId,
        amount: orderData.amount,
        currency: orderData.currency,
        name: "AYANA",
        description: `${orderData.plan_name} (${orderData.billing === "year" ? "Annual" : "Monthly"})`,
        image: "/ayana_logo.png",
        order_id: orderData.order_id,

        handler: async function (response) {
          // response contains: razorpay_payment_id, razorpay_order_id, razorpay_signature
          try {
            const { data } = await api.post("/payments/razorpay/verify", {
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
            });
            onSuccess?.({
              plan: data.plan || orderData.plan,
              billing: data.billing || orderData.billing,
              status: data.status,
            });
          } catch (err) {
            const msg =
              err?.response?.data?.detail ||
              "Payment verification failed. Please contact support if you were charged.";
            onError?.(msg);
          }
        },

        prefill: {
          name: userInfo.name || "",
          email: userInfo.email || "",
          contact: userInfo.phone || "",
        },

        notes: {
          plan: orderData.plan || "",
          billing: orderData.billing || "",
        },

        theme: {
          color: "#2C4C3B",   // AYANA primary green
        },

        modal: {
          ondismiss: function () {
            onDismiss?.();
          },
          escape: true,
          confirm_close: true,
        },
      };

      const rzp = new window.Razorpay(options);

      rzp.on("payment.failed", function (response) {
        const desc =
          response?.error?.description ||
          response?.error?.reason ||
          "Payment failed. Please try again.";
        onError?.(desc);
      });

      rzp.open();
    },
    [onSuccess, onError, onDismiss]
  );

  return { openRazorpayCheckout };
}
