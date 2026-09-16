import { useEffect, useState } from 'react';
import { Mail, ShieldCheck, Loader2 } from 'lucide-react';
import { api, formatAxiosError } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export const EmailVerificationCard = ({ user, onVerified, testid = 'email-verification' }) => {
  const [challenge, setChallenge] = useState(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [wait, setWait] = useState(0);
  useEffect(() => { setChallenge(null); setCode(''); setError(''); }, [user?.email]);
  useEffect(() => { if (!wait) return; const timer = setTimeout(() => setWait(wait - 1), 1000); return () => clearTimeout(timer); }, [wait]);
  const send = async () => {
    setBusy(true); setError('');
    try { const { data } = await api.post('/auth/email/request'); setChallenge(data.challenge_id); setCode(''); setWait(data.retry_after_seconds || 60); }
    catch (e) { setError(formatAxiosError(e)); }
    finally { setBusy(false); }
  };
  const verify = async (e) => {
    e.preventDefault(); setBusy(true); setError('');
    try { await api.post('/auth/email/verify', { challenge_id: challenge, code }); await onVerified?.(); setChallenge(null); }
    catch (e) { setError(formatAxiosError(e)); }
    finally { setBusy(false); }
  };
  return <section className="rounded-2xl border border-ayana-line bg-white p-5 space-y-3" data-testid={testid}>
    <div className="flex items-center gap-3"><Mail className="w-5 h-5 text-ayana-primary" /><div className="min-w-0"><h2 className="font-semibold text-sm" data-testid={`${testid}-title`}>Email verification</h2><p className="text-sm text-ayana-secondary break-all" data-testid={`${testid}-address`}>{user?.email}</p></div></div>
    {user?.email_verified_at ? <p className="flex gap-2 text-sm text-green-700" data-testid={`${testid}-verified`}><ShieldCheck className="w-4 h-4" />Email verified</p> : <>
      <p className="text-sm text-ayana-secondary" data-testid={`${testid}-explanation`}>We email your verification code. Your WhatsApp number is only for care updates—no mobile OTP.</p>
      {challenge && <form onSubmit={verify} className="flex flex-wrap gap-2" data-testid={`${testid}-form`}><Input aria-label="Email verification code" autoComplete="one-time-code" inputMode="numeric" value={code} onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="6-digit email code" data-testid={`${testid}-code`} className="flex-1 min-w-[150px]" /><Button disabled={busy || code.length !== 6} data-testid={`${testid}-confirm`}>Verify email</Button></form>}
      <Button variant="outline" type="button" onClick={send} disabled={busy || wait > 0} data-testid={`${testid}-send`}>{busy && <Loader2 className="mr-2 w-4 h-4 animate-spin" />}{wait ? `Resend in ${wait}s` : challenge ? 'Resend email code' : 'Send email code'}</Button>
    </>}
    {error && <p role="alert" className="text-sm text-red-700" data-testid={`${testid}-error`}>{error}</p>}
  </section>;
};