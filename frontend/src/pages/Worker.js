import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';

export default function Worker() {
  const { logout } = useAuth();
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['staff-delivery-status'],
    queryFn: () => api.get('/admin/delivery-status').then(r => r.data),
    refetchInterval: 60000,
  });
  return <main className="max-w-4xl mx-auto px-6 py-10">
    <div className="flex items-center justify-between gap-4">
      <h1 className="text-2xl font-semibold">Delivery status</h1>
      <button onClick={logout} className="underline">Sign out</button>
    </div>
    <p className="mt-2">Message delivery states for the last 24 hours.</p>
    {isLoading && <p role="status">Loading delivery status…</p>}
    {isError && <p role="alert">Could not refresh delivery status. <button onClick={() => refetch()} className="underline">Retry</button></p>}
    {data && <>
      <p className="my-4 text-sm">Last updated: {new Date(data.checked_at).toLocaleString()}</p>
      {Object.keys(data.counts).length ? <table className="w-full text-left">
        <thead><tr><th scope="col">Status</th><th scope="col">Messages</th></tr></thead>
        <tbody>{Object.entries(data.counts).map(([state, count]) => <tr key={state} className="border-t"><td className="py-3 capitalize">{state}</td><td>{count}</td></tr>)}</tbody>
      </table> : <p>No message attempts recorded in this period.</p>}
    </>}
  </main>;
}
