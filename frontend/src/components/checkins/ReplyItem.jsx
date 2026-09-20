import { useEffect, useRef } from 'react';
import { api } from '@/lib/api';
import { VoiceReply } from './VoiceReply';

export const ReplyItem = ({ reply, focused = false }) => {
  const ref = useRef(null);
  useEffect(() => { if (focused) ref.current?.scrollIntoView({ block: 'center', behavior: 'smooth' }); }, [focused]);
  useEffect(() => {
    const observer = new IntersectionObserver(entries => {
      if (entries.some(e => e.isIntersecting)) {
        api.post('/replies/read', { ids: [reply.id] }).catch(() => {});
        observer.disconnect();
      }
    });
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, [reply.id]);
  const notifications = reply.notifications || [];
  return <div ref={ref} id={`reply-${reply.id}`} className={`border-l-2 pl-4 py-2 space-y-3 min-w-0 ${focused ? 'border-ayana-gold bg-ayana-bg/70' : 'border-ayana-primary/30'}`} data-testid={`checkin-reply-${reply.id}`}>
    <p className="text-xs text-ayana-secondary" data-testid={`reply-time-${reply.id}`}>Replied {reply.display_time}</p>
    {reply.is_voice ? <VoiceReply reply={reply} /> : <p className="whitespace-pre-wrap break-words text-sm" data-testid={`reply-text-${reply.id}`}>{reply.body}</p>}
    {notifications.length > 0 && <div className="space-y-1" data-testid={`reply-notifications-${reply.id}`}>{notifications.map((n, i) => <p key={`${n.recipient_id}-${i}`} className="text-xs text-ayana-secondary" data-testid={`reply-recipient-${reply.id}-${i}`}>Family update: {n.status?.replace(/_/g, ' ')}{n.status === 'accepted' ? ' · awaiting delivery' : ''}{n.audio_status ? ` · Audio: ${n.audio_status}` : ''}{n.email_status ? ` · Email: ${n.email_status}` : ''}</p>)}</div>}
  </div>;
};