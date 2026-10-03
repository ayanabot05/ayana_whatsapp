import React from 'react';
import { Plus, Trash2, Calendar, Heart, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'
];

export const SpecialDatesEditor = ({ specialDates = [], onChange, prefix = 'pd' }) => {
  const dates = specialDates || [];

  const update = (index, patch) => {
    const next = dates.map((d, i) => (i === index ? { ...d, ...patch } : d));
    onChange(next);
  };

  const remove = (index) => {
    onChange(dates.filter((_, i) => i !== index));
  };

  const add = (kind) => {
    const newItem = {
      kind,
      title: kind === 'birthday' ? 'Birthday' : kind === 'anniversary' ? 'Wedding Anniversary' : '',
      month: 1,
      day: 1,
      note: '',
      send_time: '09:00',
      active: true,
    };
    onChange([...dates, newItem]);
  };

  const hasBirthday = dates.some(d => d.kind === 'birthday');
  const hasAnniversary = dates.some(d => d.kind === 'anniversary');

  return (
    <div className="space-y-4" data-testid={`${prefix}-special-dates`}>
      <p className="text-xs text-ayana-secondary">
        AYANA automatically sends warm personal wishes on these days with your custom note.
      </p>

      {dates.length === 0 ? (
        <div className="rounded-lg border border-dashed border-ayana-line p-4 text-center text-sm text-gray-500">
          No special dates added yet. Add a birthday or anniversary below!
        </div>
      ) : (
        <div className="space-y-3">
          {dates.map((item, index) => {
            const maxDays = [2, 4, 6, 9, 11].includes(item.month) ? (item.month === 2 ? 29 : 30) : 31;
            return (
              <article
                key={index}
                className="rounded-lg border border-ayana-line bg-white p-4 space-y-3"
                data-testid={`${prefix}-special-date-${index}`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ayana-line pb-2">
                  <div className="flex items-center gap-2">
                    {item.kind === 'birthday' && <Calendar className="w-4 h-4 text-amber-500" />}
                    {item.kind === 'anniversary' && <Heart className="w-4 h-4 text-rose-500" />}
                    {item.kind === 'special' && <Sparkles className="w-4 h-4 text-purple-500" />}
                    <span className="text-xs font-semibold uppercase tracking-wider text-ayana-primary">
                      {item.kind === 'birthday' ? 'Birthday' : item.kind === 'anniversary' ? 'Anniversary' : 'Special Event'}
                    </span>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs text-red-500 hover:text-red-700 hover:bg-red-50"
                    onClick={() => remove(index)}
                    data-testid={`${prefix}-special-date-remove-${index}`}
                  >
                    <Trash2 className="w-3.5 h-3.5 mr-1" /> Remove
                  </Button>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {item.kind === 'special' && (
                    <label className="text-xs font-medium sm:col-span-3">
                      Event name *
                      <input
                        type="text"
                        placeholder="e.g. Housewarming, Retirement"
                        value={item.title || ''}
                        onChange={e => update(index, { title: e.target.value })}
                        className="mt-1 w-full rounded-lg border border-ayana-line bg-white px-2.5 py-1.5 text-sm"
                        data-testid={`${prefix}-special-date-title-${index}`}
                      />
                    </label>
                  )}

                  <label className="text-xs font-medium">
                    Month
                    <select
                      value={item.month}
                      onChange={e => {
                        const m = parseInt(e.target.value, 10);
                        const limit = [2, 4, 6, 9, 11].includes(m) ? (m === 2 ? 29 : 30) : 31;
                        update(index, { month: m, day: Math.min(item.day, limit) });
                      }}
                      className="mt-1 w-full rounded-lg border border-ayana-line bg-white px-2.5 py-1.5 text-sm"
                      data-testid={`${prefix}-special-date-month-${index}`}
                    >
                      {MONTHS.map((m, mi) => (
                        <option key={mi + 1} value={mi + 1}>
                          {m}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="text-xs font-medium">
                    Day
                    <select
                      value={item.day}
                      onChange={e => update(index, { day: parseInt(e.target.value, 10) })}
                      className="mt-1 w-full rounded-lg border border-ayana-line bg-white px-2.5 py-1.5 text-sm"
                      data-testid={`${prefix}-special-date-day-${index}`}
                    >
                      {Array.from({ length: maxDays }, (_, i) => i + 1).map(d => (
                        <option key={d} value={d}>
                          {d}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="text-xs font-medium">
                    Send wish at
                    <input
                      type="time"
                      value={item.send_time || '09:00'}
                      onChange={e => update(index, { send_time: e.target.value })}
                      className="mt-1 w-full rounded-lg border border-ayana-line bg-white px-2.5 py-1.5 text-sm"
                      data-testid={`${prefix}-special-date-time-${index}`}
                    />
                  </label>

                  <label className="text-xs font-medium sm:col-span-3">
                    Personal note / wish (sent along with the greetings)
                    <input
                      type="text"
                      placeholder="e.g. Wishing you good health and endless happiness!"
                      maxLength={300}
                      value={item.note || ''}
                      onChange={e => update(index, { note: e.target.value })}
                      className="mt-1 w-full rounded-lg border border-ayana-line bg-white px-2.5 py-1.5 text-sm"
                      data-testid={`${prefix}-special-date-note-${index}`}
                    />
                  </label>
                </div>
              </article>
            );
          })}
        </div>
      )}

      <div className="flex flex-wrap gap-2 pt-1">
        {!hasBirthday && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => add('birthday')}
            data-testid={`${prefix}-add-birthday`}
          >
            <Plus className="w-3.5 h-3.5 mr-1 text-amber-500" /> Add Birthday
          </Button>
        )}
        {!hasAnniversary && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => add('anniversary')}
            data-testid={`${prefix}-add-anniversary`}
          >
            <Plus className="w-3.5 h-3.5 mr-1 text-rose-500" /> Add Anniversary
          </Button>
        )}
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={dates.length >= 8}
          onClick={() => add('special')}
          data-testid={`${prefix}-add-special`}
        >
          <Plus className="w-3.5 h-3.5 mr-1 text-purple-500" /> Add Special Event / Date
        </Button>
      </div>
    </div>
  );
};
