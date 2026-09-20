import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CheckinsView } from './CheckinsView';
import { api } from '@/lib/api';

const mockSetParams = jest.fn();

jest.mock('react-router-dom', () => ({
  useSearchParams: () => [new URLSearchParams('tab=checkins&date=2026-02-10'), mockSetParams],
}));

jest.mock('@/lib/api', () => ({
  api: { get: jest.fn(), post: jest.fn() },
  formatAxiosError: () => 'error',
}));

beforeAll(() => {
  global.IntersectionObserver = class {
    constructor() {}
    observe() {}
    disconnect() {}
    unobserve() {}
  };
});

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CheckinsView
        parents={[
          { id: 'dad-1', preferred_name: 'Dad', name: 'Dad', timezone: 'Asia/Kolkata' },
          { id: 'mom-1', preferred_name: 'Mom', name: 'Mom', timezone: 'Asia/Kolkata' },
        ]}
        catByKey={{ lunch: { label: 'Lunch' }, medicine: { label: 'Medicine' }, reengagement: { label: 'Re-engagement' } }}
      />
    </QueryClientProvider>
  );
}

test('shows context-linked lunch/reengagement replies while medicine stays unanswered and general is unassigned', async () => {
  api.get.mockResolvedValue({
    data: {
      alerts: [],
      parents: [
        {
          parent_id: 'dad-1',
          name: 'Dad',
          relationship: 'father',
          timezone: 'Asia/Kolkata',
          days: [
            {
              day_key: '2026-02-10',
              total: 3,
              replied: 2,
              messages: [
                { id: 'm-med', time: '09:00 AM', category: 'medicine', body: 'Medicine check', status: 'sent', replies: [] },
                { id: 'm-lunch', time: '01:00 PM', category: 'lunch', body: 'Lunch check', status: 'sent', replies: [{ id: 'r-lunch', display_time: '10 Feb, 01:10 PM IST', body: 'Had lunch' }] },
                { id: 'm-re', time: '07:00 PM', category: 'reengagement', body: 'Checking in', status: 'sent', replies: [{ id: 'r-re', display_time: '10 Feb, 07:05 PM IST', body: 'I am fine' }] },
              ],
              general_replies: [{ id: 'r-gen', display_time: '10 Feb, 08:00 PM IST', body: 'Call me later' }],
              late_replies: [],
            },
          ],
        },
        {
          parent_id: 'mom-1',
          name: 'Mom',
          relationship: 'mother',
          timezone: 'Asia/Kolkata',
          days: [{ day_key: '2026-02-10', total: 0, replied: 0, messages: [], general_replies: [], late_replies: [] }],
        },
      ],
    },
  });

  renderView();

  await waitFor(() => expect(api.get).toHaveBeenCalled());
  expect(await screen.findByText('No confirmation for this medicine')).toBeInTheDocument();
  expect(await screen.findByText('General message · not assigned to a check-in')).toBeInTheDocument();
  expect(screen.getByText('Had lunch')).toBeInTheDocument();
  expect(screen.getByText('I am fine')).toBeInTheDocument();
  expect(screen.getByTestId('parent-name-mom-1')).toBeInTheDocument();
});
