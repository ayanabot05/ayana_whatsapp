import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { careType } from '@/lib/carePlan';

const choices = [['water', 'Water'], ['tea_check', 'Tea / coffee'], ['walk_check', 'Walking / jogging'], ['bp_check', 'BP check'], ['sugar_check', 'Sugar check'], ['health_check', 'General health'], ['afternoon_checkin', 'Afternoon rest']];
export const ActivityEditor = ({ messages, onChange, limit, prefix }) => {
  const rows = messages.map((m, i) => ({ ...m, index: i })).filter(m => careType(m.category) === 'activity');
  const update = (i, key, value) => onChange(messages.map((m, n) => n === i ? { ...m, [key]: value, type: 'activity' } : m));
  const count = rows.filter(m => m.category !== 'water').length;
  return <div className="space-y-3" data-testid={`${prefix}-activities`}>
    <p className="text-xs text-ayana-secondary" data-testid={`${prefix}-activity-limit`}>Water included · {count} / {limit} additional daily activities</p>
    {rows.map(m => <div key={m.index} className="flex flex-wrap gap-2 items-center" data-testid={`${prefix}-activity-${m.index}`}><select value={m.category} onChange={e => update(m.index, 'category', e.target.value)} className="border border-ayana-line rounded-lg p-2 flex-1 min-w-0 bg-white text-sm" data-testid={`${prefix}-activity-category-${m.index}`}>{!choices.some(([v]) => v === m.category) && <option value={m.category}>{m.category.replace(/_/g, ' ')}</option>}{choices.map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select><input type="time" value={m.time} onChange={e => update(m.index, 'time', e.target.value)} className="border border-ayana-line rounded-lg p-2 bg-white text-sm" data-testid={`${prefix}-activity-time-${m.index}`} /><Button type="button" variant="ghost" size="icon" aria-label="Remove activity" data-testid={`${prefix}-activity-remove-${m.index}`} onClick={() => onChange(messages.filter((_, i) => i !== m.index))}><Trash2 className="w-4 h-4" /></Button></div>)}
    <Button type="button" variant="outline" disabled={count >= limit && rows.some(m => m.category === 'water')} data-testid={`${prefix}-activity-add`} onClick={() => onChange([...messages, { category: rows.some(m => m.category === 'water') ? 'tea_check' : 'water', type: 'activity', time: '11:00' }])}><Plus className="w-4 h-4 mr-2" />Add activity</Button>
  </div>;
};