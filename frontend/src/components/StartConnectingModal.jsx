import { useState } from "react";
import { Link } from "react-router-dom";
import { X, ArrowRight, MessageCircle, Heart } from "lucide-react";
import { Logo } from "@/components/Logo";

/**
 * StartConnectingModal — warm popup that appears when "Start Connecting"
 * is clicked on the Landing page. Offers sign up / log in paths.
 */
export function StartConnectingModal({ open, onClose }) {
  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-[100] bg-black/40 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal */}
      <div className="fixed inset-0 z-[101] flex items-center justify-center p-4">
        <div
          className="relative w-full max-w-md bg-white rounded-3xl shadow-2xl border border-ayana-line overflow-hidden animate-fade-up"
          role="dialog"
          aria-modal="true"
          aria-label="Start connecting with AYANA"
          data-testid="start-connecting-modal"
        >
          {/* Warm gradient header */}
          <div
            className="relative px-8 pt-8 pb-6 text-white"
            style={{ background: "linear-gradient(135deg, #E8B84B 0%, #D4960A 45%, #E8590C 100%)" }}
          >
            <div className="absolute -top-10 -right-10 w-40 h-40 rounded-full blur-3xl" style={{ background: "rgba(255,255,255,0.18)" }} />
            <button
              onClick={onClose}
              className="absolute top-4 right-4 w-8 h-8 rounded-full bg-white/20 hover:bg-white/30 flex items-center justify-center transition-colors"
              aria-label="Close"
              data-testid="start-connecting-modal-close"
            >
              <X className="w-4 h-4 text-white" />
            </button>

            <div className="relative">
              <Logo size={36} showWord={false} />
              <h2 className="font-display text-2xl font-bold mt-4 leading-tight">
                Start your parents' care circle today
              </h2>
              <p className="text-white/85 text-sm mt-2 leading-relaxed">
                In a few minutes, your parent will start receiving warm daily hellos on WhatsApp, in their language.
              </p>
            </div>
          </div>

          {/* Body */}
          <div className="px-8 py-6 space-y-4">
            <div className="flex items-start gap-3">
              <span className="icon-well-gold w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5">
                <MessageCircle className="w-4 h-4" />
              </span>
              <p className="text-sm text-ayana-secondary leading-relaxed">
                No app for your parents. They reply on normal WhatsApp with one tap or a voice note.
              </p>
            </div>
            <div className="flex items-start gap-3">
              <span className="icon-well-gold w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5">
                <Heart className="w-4 h-4" />
              </span>
              <p className="text-sm text-ayana-secondary leading-relaxed">
                Free trial included. Set up takes under 5 minutes.
              </p>
            </div>

            <Link
              to="/signup"
              data-testid="start-connecting-signup"
              className="btn-saffron btn-tactile w-full flex items-center justify-center gap-2 px-6 py-3.5 rounded-full font-semibold text-base mt-2"
            >
              Create your account <ArrowRight className="w-4 h-4" strokeWidth={2.5} />
            </Link>

            <p className="text-center text-sm text-ayana-secondary">
              Already have an account?{" "}
              <Link
                to="/login"
                data-testid="start-connecting-login"
                className="font-semibold text-ayana-gold hover:text-ayana-accent transition-colors"
              >
                Log in
              </Link>
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
