import { Navigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, formatAxiosError } from '@/lib/api';

export default function Replies() {
  const { replyId } = useParams();
  const { data, error, isLoading } = useQuery({ queryKey: ['reply-redirect', replyId], queryFn: () => api.get(`/replies/${replyId}`).then(r => r.data), enabled: !!replyId });
  if (replyId && isLoading) return <p role="status" className="p-8" data-testid="reply-redirect-loading">Opening your check-in…</p>;
  if (error) return <p role="alert" className="p-8" data-testid="reply-redirect-error">{formatAxiosError(error)}</p>;
  const query = new URLSearchParams({ tab: 'checkins' });
  if (data) { query.set('parent', data.parent_id); query.set('date', data.local_date); query.set('reply', data.id); }
  return <Navigate to={`/dashboard?${query}`} replace />;
}