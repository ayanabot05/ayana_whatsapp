import { useState, useEffect } from 'react';
import { ScheduleEditor } from '@/components/ScheduleEditor';
import { MedicineEditor } from '@/components/care/MedicineEditor';
import { ActivityEditor } from '@/components/care/ActivityEditor';
import { SafetyEditor } from '@/components/care/SafetyEditor';
import { SpecialDatesEditor } from '@/components/care/SpecialDatesEditor';
import { PhoneInput } from '@/components/PhoneInput';
import { TIMEZONES, COUNTRIES } from '@/lib/constants';
import { normalizeMessages, CHECKINS } from '@/lib/carePlan';
import { FALLBACK_LANGUAGES, FALLBACK_MEDICINE_SHAPES, FALLBACK_MEDICINE_COLORS, FALLBACK_MEDICINE_TIMINGS } from '@/lib/fallbackConfig';

export const blankParentForm = () => ({
  name: '',
  relationship: 'mother',
  phone: '+91',
  language: 'en',
  country: 'IN',
  city: '',
  timezone: 'Asia/Kolkata',
  preferred_name: '',
  nicknames: [],
  other_parent_name: '',
  notes: '',
  special_dates: [],
  activity_window_start: '06:00',
  activity_window_end: '22:00',
  auto_activity_detection: false,
  medicine_list: [],
  habits: {},
  messages: [{ category: 'water', type: 'activity', time: '11:00' }],
  reengagement_hours: 4
});

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

  const selectedCountry = COUNTRIES.find(c => c.code === (form.country || 'IN')) || COUNTRIES[0];
  const cities = selectedCountry.cities || [];
  const [customCity, setCustomCity] = useState(!cities.includes(form.city || '') && !!form.city);

  const [nicknamesText, setNicknamesText] = useState(() => (form.nicknames || []).join(', '));
  useEffect(() => {
    const currentParsed = nicknamesText.split(',').map(s => s.trim()).filter(Boolean).slice(0, 3);
    const formArr = form.nicknames || [];
    if (JSON.stringify(currentParsed) !== JSON.stringify(formArr)) {
      setNicknamesText(formArr.join(', '));
    }
  }, [form.nicknames]);

  const textField = (key, label, required = false) => (
    <label className="text-sm font-medium" key={key}>
      {label}{required ? ' *' : ''}
      <input required={required} value={form[key] || ''} onChange={e => edit(key, e.target.value)} className={input} data-testid={t(key)} />
    </label>
  );

  return (
    <div className="space-y-9 min-w-0" data-testid={t('care-form')}>
      {/* (iv) Parent details */}
      <section className="space-y-4" data-testid={t('parent-profile')}>
        <h3 className="font-display text-lg border-b border-ayana-line pb-3">Parent details</h3>
        <div className="grid sm:grid-cols-2 gap-4">
          {textField('name', 'Their name', true)}
          <label className="text-sm font-medium">
            Relationship
            <select value={form.relationship} onChange={e => edit('relationship', e.target.value)} className={input} data-testid={t('relationship')}>
              <option value="mother">Mother</option>
              <option value="father">Father</option>
            </select>
          </label>

          {/* Country -> City Dropdown */}
          <label className="text-sm font-medium">
            Country *
            <select
              value={form.country || 'IN'}
              onChange={e => {
                const code = e.target.value;
                const found = COUNTRIES.find(c => c.code === code) || COUNTRIES[0];
                edit('country', code);
                if (found.defaultTz) edit('timezone', found.defaultTz);
                if (found.cities && found.cities[0] !== 'Other') {
                  edit('city', found.cities[0]);
                  setCustomCity(false);
                } else {
                  edit('city', '');
                  setCustomCity(true);
                }
              }}
              className={input}
              data-testid={t('country')}
            >
              {COUNTRIES.map(c => (
                <option key={c.code} value={c.code}>{c.name}</option>
              ))}
            </select>
          </label>

          <label className="text-sm font-medium">
            City *
            {!customCity ? (
              <select
                value={form.city || ''}
                onChange={e => {
                  if (e.target.value === 'Other') {
                    setCustomCity(true);
                    edit('city', '');
                  } else {
                    edit('city', e.target.value);
                  }
                }}
                className={input}
                data-testid={t('city-select')}
              >
                <option value="">Select city</option>
                {cities.map(ct => (
                  <option key={ct} value={ct}>{ct}</option>
                ))}
              </select>
            ) : (
              <div className="flex gap-2">
                <input
                  required
                  placeholder="Enter city"
                  value={form.city || ''}
                  onChange={e => edit('city', e.target.value)}
                  className={input}
                  data-testid={t('city')}
                />
                {cities.length > 1 && (
                  <button
                    type="button"
                    onClick={() => setCustomCity(false)}
                    className="mt-1.5 px-3 py-1 text-xs border rounded-lg bg-gray-50 hover:bg-gray-100"
                  >
                    List
                  </button>
                )}
              </div>
            )}
          </label>

          <label className="text-sm font-medium">
            Parent’s timezone
            <select value={form.timezone} onChange={e => edit('timezone', e.target.value)} className={input} data-testid={t('timezone')}>
              {TIMEZONES.map(z => <option key={z.value} value={z.value}>{z.label}</option>)}
            </select>
          </label>

          <label className="text-sm font-medium">
            WhatsApp number
            <PhoneInput value={form.phone} onChange={v => edit('phone', v)} testid={t('phone')} />
          </label>

          <label className="text-sm font-medium">
            Language
            <select value={form.language} onChange={e => edit('language', e.target.value)} className={input} data-testid={t('language')}>
              {languages.map(l => <option key={l.code} value={l.code}>{l.label}</option>)}
            </select>
          </label>

          {textField('preferred_name', 'Preferred name')}

          {/* Nicknames collected up-front */}
          <label className="text-sm font-medium">
            Nicknames (up to 3, comma separated)
            <input
              className={input}
              placeholder="e.g. Amma, Mummy, Ammu"
              value={nicknamesText}
              onChange={e => {
                const val = e.target.value;
                setNicknamesText(val);
                const parsed = val.split(',').map(s => s.trim()).filter(Boolean).slice(0, 3);
                edit('nicknames', parsed);
              }}
              onBlur={() => {
                const parsed = nicknamesText.split(',').map(s => s.trim()).filter(Boolean).slice(0, 3);
                setNicknamesText(parsed.join(', '));
                edit('nicknames', parsed);
              }}
              data-testid={t('nicknames')}
            />
          </label>

          {/* Other parent name (Mom/Dad) */}
          {textField('other_parent_name', form.relationship === 'mother' ? "Father's name (Other parent)" : "Mother's name (Other parent)")}

          <label className="text-sm sm:col-span-2 font-medium">
            Notes & preferences
            <textarea
              placeholder="Any medical conditions, routines, or specific preferences..."
              value={form.notes || ''}
              onChange={e => edit('notes', e.target.value)}
              className={input}
              rows={2}
              data-testid={t('notes')}
            />
          </label>
        </div>

        {/* Quiet hours / Message window */}
        <details className="border-t border-ayana-line pt-3" data-testid={t('quiet-hours-details')} open>
          <summary className="text-sm font-medium cursor-pointer text-ayana-primary" data-testid={t('quiet-hours-toggle')}>
            Quiet hours & message window
          </summary>
          <p className="text-xs text-gray-500 mt-1">AYANA will only send messages between these hours in parent&apos;s timezone.</p>
          <div className="grid sm:grid-cols-2 gap-4 pt-3">
            {['activity_window_start', 'activity_window_end'].map(key => (
              <label key={key} className="text-sm font-medium">
                {key.endsWith('start') ? 'Messages start from' : 'Messages stop after'}
                <input
                  type="time"
                  value={form[key] || ''}
                  onChange={e => edit(key, e.target.value)}
                  className={input}
                  data-testid={t(key)}
                />
              </label>
            ))}
          </div>
        </details>
      </section>

      {/* (v) Events & special dates */}
      <section className="space-y-4" data-testid={t('events-special-dates')}>
        <h3 className="font-display text-lg border-b border-ayana-line pb-3">Events & special dates</h3>
        <SpecialDatesEditor
          specialDates={form.special_dates || []}
          onChange={v => edit('special_dates', v)}
          prefix={idPrefix}
        />
      </section>

      {/* 1. Daily check-ins */}
      <section className="space-y-4" data-testid={t('daily-checkins')}>
        <h3 className="font-display text-lg border-b border-ayana-line pb-3">1. Daily check-ins</h3>
        <ScheduleEditor messages={messages} setMessages={setMessages} categories={CHECKINS.map(key => ({ key, label: titles[key], type: 'checkin' }))} maxCheckins={limits?.checkins || 2} />
      </section>

      {/* 2. Daily activities */}
      <section className="space-y-4" data-testid={t('daily-activities')}>
        <h3 className="font-display text-lg border-b border-ayana-line pb-3">2. Daily activities</h3>
        <ActivityEditor messages={messages} onChange={setMessages} limit={limits?.activities || 0} prefix={idPrefix} />
      </section>

      {/* 3. Medicines */}
      <section className="space-y-4" data-testid={t('medicine-section')}>
        <h3 className="font-display text-lg border-b border-ayana-line pb-3">3. Medicines</h3>
        <MedicineEditor medicines={form.medicine_list || []} onChange={v => edit('medicine_list', v)} max={maxMeds} prefix={idPrefix} shapes={config?.medicine_shapes || FALLBACK_MEDICINE_SHAPES} colors={config?.medicine_colors || FALLBACK_MEDICINE_COLORS} timings={config?.medicine_timings || FALLBACK_MEDICINE_TIMINGS} />
      </section>

      {/* 4. Safety checks (vi) */}
      <section className="space-y-4" data-testid={t('safety-section')}>
        <h3 className="font-display text-lg border-b border-ayana-line pb-3">4. Safety checks</h3>
        <SafetyEditor
          messages={messages}
          onChange={setMessages}
          prefix={idPrefix}
          otherParentName={form.other_parent_name}
          parentRelationship={form.relationship}
        />
      </section>
    </div>
  );
};