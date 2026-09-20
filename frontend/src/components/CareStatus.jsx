import { useQuery } from '@tanstack/react-query';
import { Clock } from 'lucide-react';
import { api } from '@/lib/api';

export const CareStatus = ({ parentId }) => {
  const { data, error } = useQuery({ queryKey: ['care-status', parentId], queryFn: () => api.get(`/parents/${parentId}/care-status`).then(r => r.data), refetchInterval: 60000 });
  if (error) return <p className="text-xs text-red-700 my-3" data-testid={`care-status-error-${parentId}`}>Care status could not be loaded.</p>;
  if (!data) return <p className="text-xs text-ayana-secondary my-3" data-testid={`care-status-loading-${parentId}`}>Checking schedule…</p>;
  return <div className="my-3 rounded-xl bg-ayana-bg border border-ayana-line p-3 text-xs space-y-1" data-testid={`care-status-${parentId}`}>
    <p className="flex items-center gap-2 font-medium" data-testid={`care-status-message-${parentId}`}><Clock className="w-3 h-3" />{data.message}</p>
    {data.next_at && <><p data-testid={`care-next-parent-${parentId}`}>Parent time: {data.next_label}</p><p className="text-ayana-secondary" data-testid={`care-next-child-${parentId}`}>Your time: {new Date(data.next_at).toLocaleString()}</p></>}
    {data.welcome && <p className="text-ayana-secondary" data-testid={`care-welcome-${parentId}`}>Parent welcome: {data.welcome.status === 'accepted' ? 'submitted, awaiting delivery confirmation' : data.welcome.status}</p>}
    {data.child_welcome && <p className="text-ayana-secondary" data-testid={`care-child-welcome-${parentId}`}>Your welcome: {data.child_welcome.status === 'accepted' ? 'submitted, awaiting delivery confirmation' : data.child_welcome.status}{data.child_welcome.detail ? ` · ${data.child_welcome.detail}` : ''}</p>}
  </div>;
};