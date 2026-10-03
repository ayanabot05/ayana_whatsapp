import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { SAFETY } from '@/lib/carePlan';

const places = [['office_return', 'Work / office'], ['market_return', 'Market'], ['shopping_return', 'Shopping'], ['temple_return', 'Temple'], ['outing_return', 'Mosque / church / other outing']];
const weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
export const SafetyEditor = ({ messages, onChange, prefix, otherParentName = '', parentRelationship = 'mother' }) => {
  const otherRole = parentRelationship === 'mother' ? 'Dad' : 'Mom';
  const otherLabel = otherParentName.trim() || otherRole;
  const rows = messages.map((m, index) => ({ ...m, index })).filter(m => SAFETY.includes(m.category));
  const edit = (index, patch) => onChange(messages.map((m, i) => i === index ? { ...m, ...patch, type: 'safety' } : m));
  return <div className="space-y-4" data-testid={`${prefix}-safety`}>
    <p className="text-xs text-ayana-secondary" data-testid={`${prefix}-safety-limit`}>
      One return check for this parent + one check asking about {otherLabel} per day · included on all plans
    </p>
    {rows.map(m => {
      const isOther = m.about === 'other_parent';
      return (
        <article key={m.index} className="border border-ayana-line rounded-lg bg-white p-4 space-y-4" data-testid={`${prefix}-safety-${m.index}`}>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ayana-line pb-2">
            <span className="text-xs font-semibold text-ayana-primary uppercase tracking-wider">
              {isOther ? `Asking about: ${otherLabel} ("Did ${otherLabel} reach home?")` : `Asking: Parent themselves ("Did you reach home?")`}
            </span>
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-600 font-medium">Ask about:</label>
              <select 
                value={m.about || 'self'} 
                onChange={e => edit(m.index, { about: e.target.value })} 
                className="text-xs border border-ayana-line rounded px-2 py-1 bg-white"
                data-testid={`${prefix}-safety-about-${m.index}`}
              >
                <option value="self">This parent</option>
                <option value="other_parent">{otherLabel} (Mom/Dad)</option>
              </select>
            </div>
          </div>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Return check weekdays">{weekdays.map((day, i) => <button type="button" key={day} aria-pressed={(m.weekdays || []).includes(i)} className={`w-10 h-10 rounded-full text-xs border transition-colors ${(m.weekdays || []).includes(i) ? 'bg-ayana-primary text-white border-ayana-primary' : 'border-ayana-line bg-white'}`} data-testid={`${prefix}-safety-day-${m.index}-${i}`} onClick={() => edit(m.index, { weekdays: (m.weekdays || []).includes(i) ? m.weekdays.filter(d => d !== i) : [...(m.weekdays || []), i].sort() })}>{day}</button>)}</div>
          <div className="grid sm:grid-cols-2 gap-3"><label className="text-sm">Expected return<input type="time" value={m.time} className="block w-full mt-1 border border-ayana-line rounded-lg bg-white p-2" data-testid={`${prefix}-safety-time-${m.index}`} onChange={e => edit(m.index, { time: e.target.value })} /></label><label className="text-sm">Returning from<select value={m.category} className="block w-full mt-1 border border-ayana-line rounded-lg bg-white p-2" data-testid={`${prefix}-safety-place-${m.index}`} onChange={e => edit(m.index, { category: e.target.value })}>{places.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
          <label className="block text-sm">Place name<input value={m.location_label || ''} maxLength={80} onChange={e => edit(m.index, { location_label: e.target.value })} placeholder="e.g. Dmart, mosque, church" className="block mt-1 w-full rounded-lg border border-ayana-line bg-white p-2" data-testid={`${prefix}-safety-label-${m.index}`} /></label>
          <div className="flex flex-wrap items-center justify-between gap-3"><label className="text-sm inline-flex items-center gap-2"><input type="checkbox" checked={m.active !== false} onChange={e => edit(m.index, { active: e.target.checked })} data-testid={`${prefix}-safety-enabled-${m.index}`} />Enabled</label><Button type="button" variant="ghost" size="sm" data-testid={`${prefix}-safety-remove-${m.index}`} onClick={() => onChange(messages.filter((_, i) => i !== m.index))}><Trash2 className="w-4 h-4 mr-2" />Remove return check</Button></div>
        </article>
      );
    })}
    <div className="flex flex-wrap gap-2">
      <Button type="button" variant="outline" disabled={rows.length >= 14} data-testid={`${prefix}-safety-add`} onClick={() => onChange([...messages, { type: 'safety', category: 'office_return', time: '18:00', weekdays: [], location_label: '', about: 'self' }])}><Plus className="w-4 h-4 mr-2" />Add return check (Parent)</Button>
      <Button type="button" variant="outline" disabled={rows.length >= 14} data-testid={`${prefix}-safety-add-other`} onClick={() => onChange([...messages, { type: 'safety', category: 'office_return', time: '19:00', weekdays: [], location_label: '', about: 'other_parent' }])}><Plus className="w-4 h-4 mr-2" />Add check for {otherLabel}</Button>
    </div>
  </div>;
};