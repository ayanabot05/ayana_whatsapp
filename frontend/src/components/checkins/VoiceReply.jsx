import { useEffect, useRef, useState } from 'react';
import { Mic, Loader2 } from 'lucide-react';
import { api, formatAxiosError } from '@/lib/api';
import { Button } from '@/components/ui/button';

export const VoiceReply = ({ reply }) => {
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  const load = async () => {
    setBusy(true); setError('');
    try {
      const { data } = await api.get(`/replies/${reply.id}/audio`, { responseType: 'blob' });
      if (active.current) setUrl(URL.createObjectURL(data));
    } catch (e) { if (active.current) setError(formatAxiosError(e)); }
    finally { if (active.current) setBusy(false); }
  };
  return <div className="space-y-3 min-w-0" data-testid={`voice-reply-${reply.id}`}>
    {url ? <audio controls autoPlay preload="metadata" src={url} className="w-full max-w-full" data-testid={`voice-player-${reply.id}`} onError={() => setError('This recording could not be played. Try loading it again.')} /> : null}
    {(!url || error) && <Button variant="outline" size="sm" disabled={busy} onClick={load} data-testid={`voice-load-${reply.id}`}>{busy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Mic className="w-4 h-4 mr-2" />}{error ? 'Retry recording' : 'Play voice note'}</Button>}
    {error && <p role="alert" className="text-sm text-red-700 break-words" data-testid={`voice-error-${reply.id}`}>{error}</p>}
    {reply.transcription && <div data-testid={`voice-transcript-${reply.id}`}><p className="text-xs text-ayana-secondary">Automatic transcript</p><p className="text-sm whitespace-pre-wrap break-words mt-1">{reply.transcription}</p></div>}
  </div>;
};