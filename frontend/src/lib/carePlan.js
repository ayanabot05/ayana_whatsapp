import { cleanHabits, cleanOptionalString } from './formHelpers';

export const CHECKINS = ['morning_wish', 'breakfast', 'lunch', 'dinner', 'goodnight', 'love_note'];
export const ACTIVITIES = ['water', 'tea_check', 'walk_check', 'bp_check', 'sugar_check', 'health_check', 'afternoon_checkin', 'how_feeling'];
export const SAFETY = ['office_return', 'market_return', 'shopping_return', 'temple_return', 'outing_return'];
export const careType = category => category === 'medicine' ? 'reminder' : SAFETY.includes(category) ? 'safety' : ACTIVITIES.includes(category) ? 'activity' : 'checkin';
export const normalizeMessages = messages => (messages || []).filter(m => m.source !== 'medicine_sync').map(m => ({ ...m, type: careType(m.category) }));

export function carePlanPayload(form, plan, schedule = {}) {
  const { messages, reengagement_hours, ...parent } = form;
  parent.habits = cleanHabits(parent.habits);
  ['birthday', 'activity_window_start', 'activity_window_end', 'vacation_start', 'vacation_end'].forEach(key => { parent[key] = cleanOptionalString(parent[key]); });
  return { parent, schedule: { parent_id: schedule.parent_id || 'new', mode: plan, messages: normalizeMessages(messages), active: schedule.active ?? true, recovery_mode: schedule.recovery_mode || false, recovery_until: schedule.recovery_until || null, reengagement_hours: reengagement_hours || 4 } };
}