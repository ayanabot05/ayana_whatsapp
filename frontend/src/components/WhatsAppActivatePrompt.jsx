import { useAuth } from '@/context/AuthContext';

export const WhatsAppActivatePrompt = ({ greeting }) => {
  const { config } = useAuth();
  const number = (config?.whatsapp_number || '').replace(/\D/g, '');
  const message = greeting || "Hi AYANA! I'm ready to start care check-ins.";
  return <div className="border-l-4 border-amber-300 pl-4 py-3 space-y-3" data-testid="whatsapp-activate-prompt">
    <p className="text-sm font-medium" data-testid="whatsapp-backup-heading">Optional WhatsApp connection backup</p>
    <p className="text-sm text-ayana-secondary" data-testid="whatsapp-backup-note">A message from your selected number opens your conversation with AYANA. Delivery status is tracked separately.</p>
    {number ? <a href={`https://wa.me/${number}?text=${encodeURIComponent(message)}`} target="_blank" rel="noreferrer" className="inline-flex px-5 py-3 rounded-full bg-ayana-primary text-white text-sm" data-testid="whatsapp-activate-link">Open my WhatsApp</a> : <p role="status" className="text-sm text-ayana-secondary" data-testid="whatsapp-backup-unconfigured">WhatsApp backup contact is not configured.</p>}
  </div>;
};