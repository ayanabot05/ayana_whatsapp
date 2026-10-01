import { useState } from 'react';
import { api, formatAxiosError } from '@/lib/api';

export function NotificationLanguage({ user, onSaved }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState('');
  const change = async (language) => {
    setBusy(true); setError(''); setSaved('');
    try {
      await api.put('/preferences', { notification_language: language });
      await onSaved();
      setSaved('Language saved. Future updates will use this language.');
    } catch (e) { setError(formatAxiosError(e)); }
    finally { setBusy(false); }
  };
  return <div className="bg-white rounded-[16px] border border-[#efe8d8] p-4 sm:p-6 space-y-2">
    <label htmlFor="notification-language" className="font-medium">Your WhatsApp update language</label>
    <p className="text-sm text-ayana-secondary">Choose the language for your notifications and AI voice summaries. Your parent's recording stays unchanged.</p>
    <select id="notification-language" disabled={busy} value={user?.preferences?.notification_language || 'en'} onChange={e => change(e.target.value)} className="border rounded-lg p-2">
      <option value="en">English</option><option value="te">తెలుగు</option><option value="hi">हिंदी</option>
    </select>
    {error && <p role="alert">{error}</p>}{saved && <p role="status">{saved}</p>}
  </div>;
}
