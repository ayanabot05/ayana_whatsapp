// components/ParentActivateShare.jsx
import { useState } from 'react';
import { Copy, Check } from 'lucide-react';

const BUSINESS_NUMBER = "917032759453";

export const ParentActivateShare = ({ parentName }) => {
  const [copied, setCopied] = useState(false);
  const message = encodeURIComponent(`Hi AYANA! This is ${parentName}, ready for daily check-ins 💛`);
  const link = `https://wa.me/${BUSINESS_NUMBER}?text=${message}`;

  const copy = async () => {
    await navigator.clipboard.writeText(link);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5 space-y-3" data-testid="parent-activate-share">
      <p className="font-medium text-ayana-text">Ask {parentName} to tap this link once</p>
      <p className="text-sm text-ayana-secondary">
        Send this link to {parentName} (SMS, call, or however's easiest) — one tap on their phone opens WhatsApp and activates reliable check-ins.
      </p>
      <div className="flex gap-2">
        <input readOnly value={link} className="flex-1 px-3 py-2 rounded-xl border border-ayana-line bg-white text-xs truncate" />
        <button onClick={copy} className="px-4 py-2 rounded-xl bg-ayana-primary text-white text-sm font-medium flex items-center gap-1.5">
          {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />} {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
};