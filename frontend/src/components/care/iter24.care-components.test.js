import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';

import { blankParentForm, blankMedicine, ParentCareForm } from '@/components/ParentCareForm';
import { MedicineEditor } from '@/components/care/MedicineEditor';
import { SafetyEditor } from '@/components/care/SafetyEditor';

jest.mock('@/components/PhoneInput', () => ({
  PhoneInput: ({ value, onChange, testid }) => (
    <input data-testid={testid} value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}));

describe('Iteration24 care components', () => {
  beforeAll(() => {
    if (!global.crypto) {
      global.crypto = {};
    }
    if (!global.crypto.randomUUID) {
      global.crypto.randomUUID = () => 'iter24-uuid';
    }
  });

  test('shared ParentCareForm renders four sections with default water activity', () => {
    const form = blankParentForm();
    const setForm = jest.fn();

    render(
      <ParentCareForm
        form={form}
        setForm={setForm}
        newMed={blankMedicine()}
        setNewMed={jest.fn()}
        config={{
          languages: [{ code: 'en', label: 'English' }],
          medicine_shapes: ['round'],
          medicine_colors: ['white'],
          medicine_timings: ['after_food'],
        }}
        limits={{ checkins: 2, reminders: 2, activities: 1 }}
        plan={{ id: 'nitya' }}
        idPrefix="iter24"
      />
    );

    expect(screen.getByTestId('iter24-parent-profile')).toBeInTheDocument();
    expect(screen.getByTestId('iter24-daily-checkins')).toBeInTheDocument();
    expect(screen.getByTestId('iter24-daily-activities')).toBeInTheDocument();
    expect(screen.getByTestId('iter24-medicine-section')).toBeInTheDocument();
    expect(screen.getByTestId('iter24-safety-section')).toBeInTheDocument();
    expect(form.messages.some((m) => m.category === 'water')).toBe(true);
  });

  test('MedicineEditor supports add and edit dose/shape/color/time', () => {
    function Wrapper() {
      const [medicines, setMedicines] = React.useState([]);
      return (
        <MedicineEditor
          medicines={medicines}
          onChange={setMedicines}
          max={3}
          prefix="iter24"
          shapes={['round', 'oval']}
          colors={['white', 'pink']}
          timings={['after_food']}
        />
      );
    }

    render(<Wrapper />);

    fireEvent.click(screen.getByTestId('iter24-medicine-add'));

    fireEvent.change(screen.getByTestId('iter24-medicine-dose-0'), { target: { value: '500mg' } });
    fireEvent.change(screen.getByTestId('iter24-medicine-shape-0'), { target: { value: 'round' } });
    fireEvent.change(screen.getByTestId('iter24-medicine-color-0'), { target: { value: 'pink' } });
    fireEvent.change(screen.getByTestId('iter24-medicine-time-0-0'), { target: { value: '09:30' } });

    expect(screen.getByTestId('iter24-medicine-dose-0').value).toBe('500mg');
    expect(screen.getByTestId('iter24-medicine-shape-0').value).toBe('round');
    expect(screen.getByTestId('iter24-medicine-color-0').value).toBe('pink');
    expect(screen.getByTestId('iter24-medicine-time-0-0').value).toBe('09:30');
  });

  test('SafetyEditor toggles weekday buttons and preserves weekly selection', () => {
    let messages = [{ type: 'safety', category: 'office_return', time: '18:00', weekdays: [0], location_label: '' }];
    const onChange = jest.fn((next) => {
      messages = next;
    });

    const { rerender } = render(
      <SafetyEditor messages={messages} onChange={onChange} prefix="iter24" />
    );

    fireEvent.click(screen.getByTestId('iter24-safety-day-0-1'));
    rerender(<SafetyEditor messages={messages} onChange={onChange} prefix="iter24" />);
    expect(messages[0].weekdays).toEqual([0, 1]);

    fireEvent.click(screen.getByTestId('iter24-safety-day-0-0'));
    rerender(<SafetyEditor messages={messages} onChange={onChange} prefix="iter24" />);
    expect(messages[0].weekdays).toEqual([1]);
  });
});
