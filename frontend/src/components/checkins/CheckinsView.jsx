import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { CalendarDays, RefreshCw, MessageCircle } from 'lucide-react';
import { api, formatAxiosError } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { ReplyItem } from './ReplyItem';

const dateAt = zone => new Intl.DateTimeFormat('en-CA', { timeZone: zone || 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
// Friendly, DISTINCT labels for the reply_status action set (incl. the safety
// states arrived / on_way / activity_done). Falls back to a generic transform
// for delivery statuses and categories, so nothing renders raw.
const STATUS_LABELS = { done: 'Done', pending: 'Not yet', skip: 'Skipped', replied: 'Replied', arrived: 'Reached home safely', on_way: 'On the way', activity_done: 'Activity done' };
const label = value => STATUS_LABELS[value] || (value || '').replace(/_/g, ' ');

export const CheckinsView = ({ parents = [], catByKey = {} }) => {
  const [params, setParams] = useSearchParams();
  const [date, setDate] = useState(() => params.get('date') || dateAt(parents[0]?.timezone));
  const parentId = params.get('parent') || '';
  const focused = params.get('reply');
  useEffect(() => { if (params.get('date')) setDate(params.get('date')); }, [params]);
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['checkins', date, parentId],
    queryFn: () => api.get('/checkins', { params: { date, ...(parentId ? { parent_id: parentId } : {}) } }).then(r => r.data),
    refetchInterval: 15000,
  });
  const filter = (key, value) => { const next = new URLSearchParams(params); next.set('tab', 'checkins'); value ? next.set(key, value) : next.delete(key); next.delete('reply'); setParams(next, { replace: true }); };
  return <section className="space-y-6 min-w-0" data-testid="unified-checkins">
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-ayana-line pb-5">
      <div><h2 className="font-display text-lg" data-testid="checkins-heading">Your parents, in their own words</h2><p className="text-sm text-ayana-secondary mt-1" data-testid="checkins-timezone">Dates and times follow each parent’s timezone.</p></div>
      <div className="flex flex-wrap items-end gap-3 min-w-0">
        <label className="text-xs text-ayana-secondary">Parent<select value={parentId} onChange={e => filter('parent', e.target.value)} className="block mt-1 border border-ayana-line rounded-lg bg-white p-2 max-w-full" data-testid="checkins-parent-filter"><option value="">Both parents</option>{parents.map(p => <option key={p.id} value={p.id}>{p.preferred_name || p.name}</option>)}</select></label>
        <label className="text-xs text-ayana-secondary"><span className="flex gap-1 items-center"><CalendarDays className="w-3 h-3" />Date</span><input type="date" value={date} onChange={e => { if (e.target.value) { setDate(e.target.value); filter('date', e.target.value); } }} className="block mt-1 rounded-lg border border-ayana-line bg-white p-2 max-w-full" data-testid="checkins-date" /></label>
        <Button variant="outline" size="icon" aria-label="Refresh check-ins" disabled={isFetching} onClick={() => refetch()} data-testid="checkins-refresh"><RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} /></Button>
      </div>
    </div>
    {isLoading && <p role="status" data-testid="checkins-loading">Loading check-ins…</p>}
    {error && <p role="alert" className="text-red-700" data-testid="checkins-error">{formatAxiosError(error)}</p>}
    {(data?.alerts || []).map(a => <div key={a.event_id} role="alert" className="border-l-4 border-red-500 py-3 px-4 text-sm" data-testid={`care-alert-${a.event_id}`}>{a.body}<Button className="ml-3" variant="outline" size="sm" data-testid={`care-alert-review-${a.event_id}`} onClick={async () => { await api.put(`/emergency-events/${a.event_id}`, { status: 'reviewed' }); refetch(); }}>Mark reviewed</Button></div>)}
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
      {(data?.parents || []).map(p => {
        const day = p.days.find(d => d.day_key === date);
        const messages = day?.messages || [];
        const general = day?.general_replies || [];
        const late = day?.late_replies || [];
        return <section key={p.parent_id} className="min-w-0 space-y-4" data-testid={`parent-timeline-${p.parent_id}`}>
          <header className="flex justify-between flex-wrap gap-2"><div><h3 className="font-display text-lg" data-testid={`parent-name-${p.parent_id}`}>{p.name}</h3><p className="text-xs text-ayana-secondary" data-testid={`parent-zone-${p.parent_id}`}>{p.relationship === 'mother' ? 'Mom' : 'Dad'} · {p.timezone}</p></div><p className="text-sm text-ayana-primary" data-testid={`parent-reply-count-${p.parent_id}`}>{day?.replied || 0} / {day?.total || 0} messages answered</p></header>
          {!messages.length && !general.length && !late.length && <p className="text-sm text-ayana-secondary py-10 border-y border-dashed border-ayana-line" data-testid={`parent-empty-${p.parent_id}`}>No messages on this date.</p>}
          {messages.map(m => <article key={m.id} className="rounded-lg bg-white border border-ayana-line p-4 sm:p-5 space-y-4 min-w-0" data-testid={`checkin-event-${m.id}`}>
            <div className="flex justify-between gap-3 flex-wrap"><div><p className="text-xs text-ayana-secondary" data-testid={`checkin-time-${m.id}`}>{m.time}</p><h4 className="font-medium mt-1" data-testid={`checkin-category-${m.id}`}>{catByKey[m.category]?.label || label(m.category)}</h4></div><span className="text-xs text-ayana-secondary" data-testid={`checkin-delivery-${m.id}`}>{label(m.delivery_status || (m.status === 'sent' ? 'accepted' : m.status))}</span></div>
            <p className="text-sm text-ayana-secondary whitespace-pre-wrap break-words" data-testid={`checkin-body-${m.id}`}>{m.body}</p>
            {m.detail && m.status !== 'sent' && <p className="text-xs text-red-700 break-words" data-testid={`checkin-failure-${m.id}`}>{m.detail}</p>}
            {m.replies?.length ? m.replies.map(r => <ReplyItem key={r.id} reply={r} focused={focused === r.id} />) : <p className="text-xs text-ayana-secondary flex items-center gap-2" data-testid={`checkin-unanswered-${m.id}`}><MessageCircle className="w-3 h-3" />{m.category === 'medicine' ? 'No confirmation for this medicine' : 'No reply to this message'}</p>}
            {m.reply_status && <p className="text-xs text-ayana-primary" data-testid={`checkin-response-${m.id}`}>{label(m.reply_status)}</p>}
          </article>)}
          {(general.length > 0 || late.length > 0) && <div className="space-y-4 py-4 border-t border-ayana-line" data-testid={`other-replies-${p.parent_id}`}><h4 className="text-sm font-medium">Other messages received</h4>{general.map(r => <div key={r.id}><p className="text-xs text-ayana-secondary mb-2" data-testid={`general-label-${r.id}`}>General message · not assigned to a check-in</p><ReplyItem reply={r} focused={focused === r.id} /></div>)}{late.map(r => <div key={r.id}><p className="text-xs text-ayana-secondary mb-2" data-testid={`late-label-${r.id}`}>Reply to an earlier {label(r.category)} message</p><ReplyItem reply={r} focused={focused === r.id} /></div>)}</div>}
        </section>;
      })}
    </div>
  </section>;
};