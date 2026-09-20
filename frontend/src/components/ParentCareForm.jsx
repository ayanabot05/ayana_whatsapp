import { ScheduleEditor } from '@/components/ScheduleEditor';
import { MedicineEditor } from '@/components/care/MedicineEditor';
import { ActivityEditor } from '@/components/care/ActivityEditor';
import { SafetyEditor } from '@/components/care/SafetyEditor';
import { PhoneInput } from '@/components/PhoneInput';
import { TIMEZONES } from '@/lib/constants';
import { normalizeMessages, CHECKINS } from '@/lib/carePlan';
import { FALLBACK_LANGUAGES, FALLBACK_MEDICINE_SHAPES, FALLBACK_MEDICINE_COLORS, FALLBACK_MEDICINE_TIMINGS } from '@/lib/fallbackConfig';

export const blankParentForm = () => ({ name: '', relationship: 'mother', phone: '+91', language: 'en', timezone: 'Asia/Kolkata', notes: '', preferred_name: '', nicknames: [], city: '', other_parent_name: '', birthday: '', stories: [], activity_window_start: '06:00', activity_window_end: '22:00', auto_activity_detection: false, medicine_list: [], habits: {}, messages: [{ category: 'water', type: 'activity', time: '11:00' }], reengagement_hours: 4 });
export const blankMedicine = () => ({ name: '', dose: '', reminder_time: '09:00', shape: '', color: '', timing: '', notes: '' });
export const COLOR_HEX = { white: '#fff', cream: '#fffdd0', yellow: '#fde68a', orange: '#fca347', pink: '#fbbfd0', red: '#f87171', purple: '#c084fc', blue: '#7dd3fc', green: '#86efac', brown: '#a07850', beige: '#d4c5a9' };
export const SHAPE_ICON = { round: '⬤', oval: '⬭', capsule: '💊', oblong: '▬', diamond: '◆', square: '■' };
const input = 'mt-1.5 w-full rounded-lg border border-ayana-line bg-white px-3 py-2 text-sm';
const titles = { morning_wish: 'Morning greeting', breakfast: 'Breakfast', lunch: 'Lunch', dinner: 'Dinner', goodnight: 'Good night', love_note: 'Love note' };

export const ParentCareForm = ({ form, setForm, config, limits, idPrefix = 'pd' }) => {
  const t = suffix => `${idPrefix}-${suffix}`;
  const edit = (key, value) => setForm(f => ({ ...f, [key]: value }));
  const messages = normalizeMessages(form.messages);
  const setMessages = value => edit('messages', value);
  const languages = config?.languages?.length ? config.languages : FALLBACK_LANGUAGES;
  const maxMeds = (limits?.reminders || 3) + (form.recovery_mode ? limits?.recovery_extra_reminders || 0 : 0);
  const textField = (key, label, required = false) => <label className="text-sm font-medium" key={key}>{label}{required ? ' *' : ''}<input required={required} value={form[key] || ''} onChange={e => edit(key, e.target.value)} className={input} data-testid={t(key)} /></label>;
  return <div className="space-y-9 min-w-0" data-testid={t('care-form')}>
    <section className="space-y-4" data-testid={t('parent-profile')}>
      <h3 className="font-display text-lg border-b border-ayana-line pb-3">Parent details</h3>
      <div className="grid sm:grid-cols-2 gap-4">{textField('name', 'Their name', true)}<label className="text-sm font-medium">Relationship<select value={form.relationship} onChange={e => edit('relationship', e.target.value)} className={input} data-testid={t('relationship')}><option value="mother">Mother</option><option value="father">Father</option></select></label>{textField('city', 'Their city', true)}<label className="text-sm font-medium">Parent’s timezone<select value={form.timezone} onChange={e => edit('timezone', e.target.value)} className={input} data-testid={t('timezone')}>{TIMEZONES.map(z => <option key={z.value} value={z.value}>{z.label}</option>)}</select></label><label className="text-sm font-medium">WhatsApp number<PhoneInput value={form.phone} onChange={v => edit('phone', v)} testid={t('phone')} /></label><label className="text-sm font-medium">Language<select value={form.language} onChange={e => edit('language', e.target.value)} className={input} data-testid={t('language')}>{languages.map(l => <option key={l.code} value={l.code}>{l.label}</option>)}</select></label>{textField('preferred_name', 'Preferred name')}{textField('other_parent_name', 'Other parent’s name')}</div>
      <details className="border-b border-ayana-line py-3" data-testid={t('personal-details')}><summary className="text-sm cursor-pointer" data-testid={t('personal-details-toggle')}>Personal details and quiet hours</summary><div className="grid sm:grid-cols-2 gap-4 pt-4">{textField('birthday', 'Birthday (MM-DD)')}<label className="text-sm">Nicknames<input className={input} value={(form.nicknames || []).join(', ')} onChange={e => edit('nicknames', e.target.value.split(',').slice(0, 3))} data-testid={t('nicknames')} /></label>{['activity_window_start', 'activity_window_end'].map(key => <label key={key} className="text-sm">{key.endsWith('start') ? 'Messages from' : 'Messages until'}<input type="time" value={form[key] || ''} onChange={e => edit(key, e.target.value)} className={input} data-testid={t(key)} /></label>)}<label className="text-sm sm:col-span-2">Notes<textarea value={form.notes || ''} onChange={e => edit('notes', e.target.value)} className={input} data-testid={t('notes')} /></label><label className="text-sm sm:col-span-2">Family stories (one per line)<textarea value={(form.stories || []).join('\n')} onChange={e => edit('stories', e.target.value.split('\n').slice(0, 5))} className={input} data-testid={t('stories')} /></label></div></details>
    </section>
    <section className="space-y-4" data-testid={t('daily-checkins')}><h3 className="font-display text-lg border-b border-ayana-line pb-3">1. Daily check-ins</h3><ScheduleEditor messages={messages} setMessages={setMessages} categories={CHECKINS.map(key => ({ key, label: titles[key], type: 'checkin' }))} maxCheckins={limits?.checkins || 2} /></section>
    <section className="space-y-4" data-testid={t('daily-activities')}><h3 className="font-display text-lg border-b border-ayana-line pb-3">2. Daily activities</h3><ActivityEditor messages={messages} onChange={setMessages} limit={limits?.activities || 0} prefix={idPrefix} /></section>
    <section className="space-y-4" data-testid={t('medicine-section')}><h3 className="font-display text-lg border-b border-ayana-line pb-3">3. Medicines</h3><MedicineEditor medicines={form.medicine_list || []} onChange={v => edit('medicine_list', v)} max={maxMeds} prefix={idPrefix} shapes={config?.medicine_shapes || FALLBACK_MEDICINE_SHAPES} colors={config?.medicine_colors || FALLBACK_MEDICINE_COLORS} timings={config?.medicine_timings || FALLBACK_MEDICINE_TIMINGS} /></section>
    <section className="space-y-4" data-testid={t('safety-section')}><h3 className="font-display text-lg border-b border-ayana-line pb-3">4. Safety checks</h3><SafetyEditor messages={messages} onChange={setMessages} prefix={idPrefix} /></section>
  </div>;
};