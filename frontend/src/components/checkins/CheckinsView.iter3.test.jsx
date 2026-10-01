import React from 'react';
import '@testing-library/jest-dom';
import { render, screen, waitFor, within } from '@testing-library/react';
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

test('shows delivery trouble separately from unanswered check-ins', async () => {
  api.get.mockResolvedValue({data:{parents:[],alerts:[],delivery_alerts:[{
    parent_id:'mom-1',day:'2026-02-10',body:'AYANA could not confirm delivery of 2 scheduled messages to Mom. Please check their phone or contact them directly.'
  }]}});
  renderView();
  expect(await screen.findByTestId('delivery-alert')).toHaveTextContent('could not confirm delivery');
  expect(screen.queryByText('Mark reviewed')).not.toBeInTheDocument();
});

test('evening reply remains in the morning card', async () => {
  api.get.mockResolvedValue({data:{parents:[{parent_id:'mom-1',name:'Mom',relationship:'mother',timezone:'Asia/Kolkata',days:[{
    day_key:'2026-02-10',total:2,replied:1,general_replies:[],late_replies:[],messages:[
      {id:'morning',time:'08:00 AM IST',category:'morning_wish',body:'Morning check-in',status:'sent',delivery_status:'read',
        replies:[{id:'late-answer',body:'I am fine, replying now',display_time:'10 Feb, 08:05 PM IST',notifications:[{recipient_id:'child',status:'delivered'}]}]},
      {id:'evening',time:'08:00 PM IST',category:'goodnight',body:'Evening check-in',status:'sent',delivery_status:'delivered',replies:[]}
    ]}]}],alerts:[]}});
  renderView();
  const morning = await screen.findByTestId('checkin-event-morning');
  const evening = screen.getByTestId('checkin-event-evening');
  expect(within(morning).getByText('I am fine, replying now')).toBeInTheDocument();
  expect(within(morning).getByText(/08:05 PM IST/)).toBeInTheDocument();
  expect(within(morning).getByTestId('reply-recipient-late-answer-0')).toHaveTextContent('Family update: delivered');
  expect(within(evening).queryByText('I am fine, replying now')).not.toBeInTheDocument();
  expect(within(evening).getByText('No reply to this message')).toBeInTheDocument();
});

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
