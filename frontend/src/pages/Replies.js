import { useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Mic, MessageCircle } from 'lucide-react';
import { Navbar } from '@/components/Navbar';
import { ReplyDetail } from '@/components/ReplyDetail';
import { api, formatAxiosError } from '@/lib/api';
import { Button } from '@/components/ui/button';

export default function Replies() {
  const { replyId } = useParams();
  const client = useQueryClient();
  const { data: replies = [], isLoading, error, refetch } = useQuery({ queryKey: ['replies-inbox'], queryFn: () => api.get('/replies').then(r => r.data), refetchInterval: 15000 });
  const onRead = useCallback(() => { client.invalidateQueries({ queryKey: ['replies-inbox'] }); client.invalidateQueries({ queryKey: ['dashboard'] }); }, [client]);
  return <div className="min-h-screen bg-ayana-bg text-ayana-text" data-testid="replies-page"><Navbar /><main className="max-w-6xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
    <Link to="/dashboard" className="inline-flex items-center gap-2 text-sm text-ayana-secondary hover:text-ayana-primary" data-testid="replies-back"><ArrowLeft className="w-4 h-4" />Back to dashboard</Link>
    <div className="my-7"><p className="text-xs uppercase tracking-[0.2em] text-ayana-secondary" data-testid="replies-eyebrow">Your family, in their words</p><h1 className="font-display text-4xl sm:text-5xl mt-2" data-testid="replies-title">Replies</h1><p className="mt-3 text-ayana-secondary" data-testid="replies-description">Read their updates, listen to their voice, and see notification status.</p></div>
    {isLoading && <p data-testid="replies-loading">Loading your family’s replies…</p>}
    {error && <div role="alert" className="p-5 border rounded-xl space-y-2" data-testid="replies-error"><p>{formatAxiosError(error)}</p><Button onClick={() => refetch()} data-testid="replies-retry">Try again</Button></div>}
    {!isLoading && !error && !replies.length && !replyId && <div className="bg-white border border-ayana-line rounded-2xl p-10 text-center" data-testid="replies-empty"><MessageCircle className="w-8 h-8 text-ayana-primary mx-auto mb-3" /><p>When your parent replies, their message will appear here.</p></div>}
    <div className="grid lg:grid-cols-[340px_minmax(0,1fr)] gap-5 items-start">
      <div className="space-y-3" data-testid="replies-list">{replies.map(r => <Link key={r.id} to={`/replies/${r.id}`} className={`block rounded-2xl border p-5 transition-colors ${r.id === replyId ? 'bg-white border-ayana-primary' : 'bg-white/70 border-ayana-line hover:border-ayana-primary/50'}`} data-testid={`reply-item-${r.id}`}><div className="flex justify-between gap-2"><span className="font-medium">{r.parent_name}</span>{!r.read_at && <span className="text-xs text-ayana-primary font-medium" data-testid={`reply-unread-${r.id}`}>Unread</span>}</div><p className="mt-2 text-sm text-ayana-secondary line-clamp-2 break-words">{r.is_voice ? <span className="inline-flex items-center gap-1"><Mic className="w-3 h-3" />Voice note</span> : r.body}</p><p className="mt-3 text-xs text-ayana-muted">{new Date(r.created_at).toLocaleString()}</p></Link>)}</div>
      <div className={`bg-white rounded-2xl border border-ayana-line min-w-0 ${replyId ? 'order-first lg:order-none' : ''}`}><ReplyDetail replyId={replyId} onRead={onRead} /></div>
    </div>
  </main></div>;
}