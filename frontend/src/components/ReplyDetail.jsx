import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Mic, Loader2 } from 'lucide-react';
import { api, formatAxiosError } from '@/lib/api';
import { Button } from '@/components/ui/button';

export const ReplyDetail = ({ replyId, onRead }) => {
  const [audioUrl, setAudioUrl] = useState('');
  const [audioError, setAudioError] = useState('');
  const [audioBusy, setAudioBusy] = useState(false);
  const { data: reply, isLoading, error, refetch } = useQuery({ queryKey: ['reply', replyId], queryFn: () => api.get(`/replies/${replyId}`).then(r => r.data), enabled: !!replyId });
  useEffect(() => { setAudioUrl(''); setAudioError(''); }, [replyId]);
  useEffect(() => () => { if (audioUrl) URL.revokeObjectURL(audioUrl); }, [audioUrl]);
  useEffect(() => { if (reply?.id) api.post('/replies/read', { ids: [reply.id] }).then(() => onRead?.()).catch(() => {}); }, [reply?.id, onRead]);
  const loadAudio = async () => {
    setAudioBusy(true); setAudioError('');
    try { const { data } = await api.get(`/replies/${replyId}/audio`, { responseType: 'blob' }); setAudioUrl(URL.createObjectURL(data)); }
    catch (e) { let message = formatAxiosError(e); if (e.response?.data instanceof Blob) { try { message = JSON.parse(await e.response.data.text()).detail || message; } catch {} } setAudioError(message); }
    finally { setAudioBusy(false); }
  };
  if (isLoading) return <p data-testid="reply-detail-loading" className="p-6">Loading reply…</p>;
  if (error) return <div role="alert" className="p-6 space-y-3" data-testid="reply-detail-error"><p>{formatAxiosError(error)}</p><Button onClick={() => refetch()} data-testid="reply-detail-retry">Try again</Button></div>;
  if (!reply) return <p className="p-6 text-ayana-secondary" data-testid="reply-detail-empty">Choose a reply to read or listen.</p>;
  return <article className="p-5 sm:p-8 space-y-5" data-testid="reply-detail">
    <div><p className="text-xs uppercase tracking-widest text-ayana-secondary" data-testid="reply-detail-category">{reply.prompt}</p><h2 className="mt-2 font-display text-lg" data-testid="reply-detail-parent">{reply.parent_name} replied</h2><p className="mt-1 text-sm text-ayana-secondary" data-testid="reply-detail-time">{reply.display_time}</p></div>
    {reply.is_voice ? <section className="space-y-3 rounded-xl bg-ayana-bg border border-ayana-line p-4" data-testid="reply-voice-section"><p className="flex items-center gap-2 font-medium" data-testid="reply-voice-title"><Mic className="w-4 h-4" />Voice note</p>{audioUrl ? <audio controls preload="metadata" src={audioUrl} className="w-full" data-testid="reply-audio-player" onError={() => setAudioError('Your browser could not play this recording.')} /> : <Button onClick={loadAudio} disabled={audioBusy} data-testid="reply-load-audio">{audioBusy ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}Load voice note</Button>}{audioError && <p role="alert" className="text-sm text-red-700" data-testid="reply-audio-error">{audioError}</p>}{reply.transcription && <><p className="text-xs text-ayana-secondary" data-testid="reply-transcript-notice">Automatic transcript—listen to confirm the words.</p><p className="whitespace-pre-wrap break-words" data-testid="reply-transcript">{reply.transcription}</p></>}</section> : <blockquote className="border-l-2 border-ayana-gold pl-5 py-2 text-lg whitespace-pre-wrap break-words" data-testid="reply-body">{reply.body}</blockquote>}
    <div className="border-t border-ayana-line pt-4 space-y-2" data-testid="reply-delivery-status"><p className="text-sm font-medium">Your notifications</p>{reply.notifications.length ? reply.notifications.map((n, i) => <p key={i} className="text-sm text-ayana-secondary" data-testid={`reply-notification-${i}`}>WhatsApp: {n.status.replace(/_/g, ' ')}{n.email_status ? ` · Email: ${n.email_status}` : ''}{n.status === 'accepted' ? ' (awaiting delivery confirmation)' : ''}</p>) : <p className="text-sm text-ayana-secondary" data-testid="reply-notification-legacy">No delivery record is available for this older reply.</p>}</div>
  </article>;
};