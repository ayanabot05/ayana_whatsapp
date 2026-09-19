// components/WhatsAppActivatePrompt.jsx
const BUSINESS_NUMBER = "917032759453"; // your display_phone_number, digits only, no +

export const WhatsAppActivatePrompt = ({ recipientLabel = "you", greeting }) => {
  const message = encodeURIComponent(
    greeting || `Hi AYANA! I'm ready to start care check-ins 💛`
  );
  const link = `https://wa.me/${BUSINESS_NUMBER}?text=${message}`;
  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5 space-y-3 text-center" data-testid="whatsapp-activate-prompt">
      <p className="font-medium text-ayana-text">One quick step to activate WhatsApp care</p>
      <p className="text-sm text-ayana-secondary">
        Tap below to send us a message on WhatsApp — this confirms {recipientLabel} want{recipientLabel === 'you' ? '' : 's'} to hear from us, so messages come through reliably.
      </p>
      <a href={link} target="_blank" rel="noreferrer"
         className="inline-flex items-center gap-2 px-6 py-3 rounded-full bg-ayana-whatsapp text-white font-medium hover:opacity-90 transition-opacity"
         data-testid="whatsapp-activate-link">
        💬 Message us on WhatsApp
      </a>
    </div>
  );
};