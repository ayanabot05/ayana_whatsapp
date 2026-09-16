import { useEffect, useState } from 'react';
import { api, formatAxiosError } from '@/lib/api';
import { PhoneInput } from '@/components/PhoneInput';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';

export const PhoneChangeDialog = ({ user, onChanged, testid = 'phone-change' }) => {
  const [open, setOpen] = useState(false);
  const [phone, setPhone] = useState(user?.phone || '');
  const [confirmed, setConfirmed] = useState(false);
  const [challenge, setChallenge] = useState(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  useEffect(() => { setPhone(user?.phone || ''); setConfirmed(false); setChallenge(null); setCode(''); setError(''); }, [open, user?.phone, user?.email]);
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setError('');
    try {
      if (!challenge) { const { data } = await api.post('/profile/phone/request', { phone, confirmed }); setChallenge(data.challenge_id); }
      else { const { data } = await api.post('/profile/phone/confirm', { challenge_id: challenge, code }); await onChanged?.(); setMessage(data.message); setOpen(false); }
    } catch (e) { setError(formatAxiosError(e)); }
    finally { setBusy(false); }
  };
  return <div className="space-y-2" data-testid={testid}>
    <Button variant="outline" type="button" onClick={() => setOpen(true)} data-testid={`${testid}-open`}>Change WhatsApp number</Button>
    {message && <p role="status" className="text-sm text-green-700" data-testid={`${testid}-success`}>{message}</p>}
    <Dialog open={open} onOpenChange={value => !busy && setOpen(value)}><DialogContent className="max-w-md" data-testid={`${testid}-dialog`}>
      <DialogHeader><DialogTitle data-testid={`${testid}-title`}>Change your WhatsApp number?</DialogTitle><DialogDescription data-testid={`${testid}-description`}>Authorize the change through your account email. This confirms your account action, not ownership of the new phone.</DialogDescription></DialogHeader>
      <form onSubmit={submit} className="space-y-4" data-testid={`${testid}-form`}>
        <p className="text-sm" data-testid={`${testid}-old`}>Current number: <strong>{user?.phone}</strong></p>
        {!challenge ? <><PhoneInput value={phone} onChange={value => { setPhone(value); setConfirmed(false); }} testid={`${testid}-new`} /><label className="flex items-start gap-2 text-sm" data-testid={`${testid}-consent-label`}><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} data-testid={`${testid}-consent`} className="mt-1" />This is my WhatsApp number. I want future care updates sent here instead of my old number.</label></> : <>
          <p className="text-sm" data-testid={`${testid}-destination`}>New number: <strong>{phone}</strong></p>
          <p className="text-sm text-ayana-secondary" data-testid={`${testid}-email`}>Enter the code emailed to {user?.email}. It expires in five minutes.</p>
          <Input value={code} onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" placeholder="Email confirmation code" aria-label="Number change email code" data-testid={`${testid}-code`} />
        </>}
        <p className="text-xs text-ayana-secondary" data-testid={`${testid}-warning`}>Old replies are not forwarded automatically. Messages already submitted to WhatsApp cannot be recalled.</p>
        {error && <p role="alert" className="text-sm text-red-700" data-testid={`${testid}-error`}>{error}</p>}
        <div className="flex flex-wrap gap-2"><Button type="submit" disabled={busy || (!challenge && (!confirmed || phone === user?.phone)) || (challenge && code.length !== 6)} data-testid={`${testid}-submit`}>{busy ? 'Please wait…' : challenge ? 'Confirm number change' : 'Email confirmation code'}</Button><Button type="button" variant="outline" disabled={busy} onClick={() => setOpen(false)} data-testid={`${testid}-cancel`}>Cancel</Button></div>
      </form>
    </DialogContent></Dialog>
  </div>;
};