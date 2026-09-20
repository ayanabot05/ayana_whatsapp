import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ArrowRight, MessageCircle } from 'lucide-react';
import { Navbar } from '@/components/Navbar';
import { Footer } from '@/components/Footer';
import { CareStatus } from '@/components/CareStatus';
import { api, formatAxiosError } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';

export default function Activation() {
  const { config, user } = useAuth();
  const { data: parents = [], error, isLoading } = useQuery({ queryKey: ['activation-parents'], queryFn: () => api.get('/parents').then(r => r.data) });
  const activation = useQuery({ queryKey: ['activation-state'], queryFn: () => api.get('/activation').then(r => r.data) });
  const phone = (config?.whatsapp_number || '').replace(/\D/g, '');
  const ready = activation.data?.whatsapp_activated;
  return <div className="min-h-screen bg-warm-cream flex flex-col"><Navbar /><main className="flex-1 w-full max-w-3xl mx-auto px-5 sm:px-8 py-12 space-y-8" data-testid="activation-page">
    <header className="space-y-3 border-b border-ayana-line pb-8"><p className="text-sm text-ayana-secondary">AYANA · Your family</p><h1 className="font-display text-4xl" data-testid="activation-heading">{ready ? 'Care is configured.' : 'Your care setup'}</h1><p className="text-ayana-secondary" data-testid="activation-description">Welcome delivery and scheduled messages are tracked separately.</p></header>
    {(isLoading || activation.isLoading) && <p role="status" data-testid="activation-loading">Loading your care setup…</p>}
    {(error || activation.error) && <p role="alert" className="text-red-700" data-testid="activation-error">{formatAxiosError(error || activation.error)}</p>}
    {!config?.whatsapp_enabled && <p role="status" className="border-l-4 border-amber-500 pl-4 text-sm" data-testid="activation-sending-disabled">Live WhatsApp sending is off. No real messages are being delivered.</p>}
    <section className="divide-y divide-ayana-line" data-testid="activation-parent-statuses">{parents.map(p => <div key={p.id} className="py-5 space-y-3"><h2 className="font-display text-lg" data-testid={`activation-parent-${p.id}`}>{p.preferred_name || p.name}</h2><CareStatus parentId={p.id} /></div>)}</section>
    {phone && <section className="border-y border-ayana-line py-6 space-y-3" data-testid="activation-child-backup"><h2 className="font-display text-lg">Your WhatsApp connection</h2><p className="text-sm text-ayana-secondary" data-testid="activation-child-phone">{user?.phone} · Optional backup if your welcome has not arrived.</p><a href={`https://wa.me/${phone}?text=${encodeURIComponent("Hi AYANA! I'm ready to start care check-ins.")}`} target="_blank" rel="noreferrer" className="inline-flex gap-2 items-center rounded-full bg-ayana-primary text-white px-5 py-3 text-sm" data-testid="activation-child-open-whatsapp"><MessageCircle className="w-4 h-4" />Open my WhatsApp</a></section>}
    <Link to="/dashboard?tab=checkins" className="inline-flex items-center gap-2 text-ayana-primary font-medium" data-testid="activation-to-dashboard">View family check-ins<ArrowRight className="w-4 h-4" /></Link>
  </main><Footer /></div>;
}