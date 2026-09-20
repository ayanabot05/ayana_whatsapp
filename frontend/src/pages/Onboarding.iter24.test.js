import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const mockNavigate = jest.fn();

jest.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}));

jest.mock('../lib/api', () => {
  const api = {
    get: jest.fn(),
    put: jest.fn(),
    post: jest.fn(),
    delete: jest.fn(),
  };
  return {
    api,
    __mockApi: api,
    formatApiError: (x) => String(x || ''),
    formatAxiosError: () => 'error',
  };
});

jest.mock('@/context/AuthContext', () => ({
  useAuth: () => ({
    user: {
      name: 'Child Tester',
      phone: '+14150001111',
      onboarding_step: 2,
      onboarding_complete: false,
      email_verified_at: '2026-01-01T00:00:00Z',
      email_verification_required: false,
    },
    config: {
      plans: [{ id: 'nitya', name: 'Nitya', limits: { parents: 1, checkins: 2, reminders: 2 } }],
      currencies: [{ code: 'USD' }],
    },
    refreshUser: jest.fn(),
  }),
}));

jest.mock('@/lib/useRazorpay', () => ({
  useRazorpay: () => ({ openRazorpayCheckout: jest.fn() }),
}));

jest.mock('@/components/ParentCareForm', () => ({
  blankMedicine: () => ({ name: '', dose: '', reminder_time: '09:00', shape: '', color: '', timing: '', notes: '' }),
  blankParentForm: () => ({
    name: '',
    relationship: 'mother',
    phone: '+91',
    language: 'en',
    timezone: 'Asia/Kolkata',
    city: '',
    medicine_list: [],
    habits: {},
    messages: [{ category: 'water', type: 'activity', time: '11:00' }],
  }),
  ParentCareForm: ({ form, setForm }) => (
    <div>
      <input
        data-testid="iter24-parent-name"
        value={form.name}
        onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
      />
      <input
        data-testid="iter24-parent-phone"
        value={form.phone}
        onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
      />
      <input
        data-testid="iter24-parent-city"
        value={form.city}
        onChange={(e) => setForm((f) => ({ ...f, city: e.target.value }))}
      />
    </div>
  ),
}));

jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

import Onboarding from './Onboarding';
import { __mockApi as mockApi } from '../lib/api';

describe('Onboarding iteration24 endpoint contract', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockApi.get.mockImplementation((url) => {
      if (url === '/payment/state') return Promise.resolve({ data: { state: { plan: 'nitya' } } });
      if (url === '/parents') return Promise.resolve({ data: [] });
      if (url === '/schedules') return Promise.resolve({ data: [] });
      return Promise.resolve({ data: {} });
    });
    mockApi.post.mockResolvedValue({ data: { parent: { id: 'p1', name: 'Amma', timezone: 'Asia/Kolkata' } } });
    mockApi.put.mockResolvedValue({ data: {} });
  });

  test('parent save on onboarding posts /care-plans (not /schedules)', async () => {
    render(<Onboarding />);

    await waitFor(() => expect(screen.getByTestId('parent-form')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('iter24-parent-name'), { target: { value: 'Amma' } });
    fireEvent.change(screen.getByTestId('iter24-parent-phone'), { target: { value: '+14158889999' } });
    fireEvent.change(screen.getByTestId('iter24-parent-city'), { target: { value: 'Hyderabad' } });
    fireEvent.click(screen.getByTestId('parent-consent'));
    fireEvent.click(screen.getByTestId('save-parent'));

    await waitFor(() => {
      expect(mockApi.post).toHaveBeenCalled();
    });

    const calledRoutes = mockApi.post.mock.calls.map((c) => c[0]);
    expect(calledRoutes).toContain('/care-plans');
    expect(calledRoutes).not.toContain('/schedules');
  });
});
