import React from 'react';
import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Worker from './Worker';
import { api } from '@/lib/api';
jest.mock('@/lib/api', () => ({api: {get: jest.fn()}}));
jest.mock('@/context/AuthContext', () => ({useAuth: () => ({logout: jest.fn()})}));

test('worker shows only aggregate delivery states', async () => {
  api.get.mockResolvedValue({data:{checked_at:'2026-09-30T10:00:00Z', counts:{delivered:8, failed:2}}});
  const client = new QueryClient({defaultOptions:{queries:{retry:false}}});
  render(<QueryClientProvider client={client}><Worker /></QueryClientProvider>);
  expect(await screen.findByRole('table')).toHaveTextContent('delivered8failed2');
  expect(api.get).toHaveBeenCalledWith('/admin/delivery-status');
  expect(screen.queryByRole('button',{name:/delete|send|edit/i})).not.toBeInTheDocument();
});
