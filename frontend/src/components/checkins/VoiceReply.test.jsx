import React from 'react';
import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
import { VoiceReply } from './VoiceReply';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() }, formatAxiosError: () => 'Recording unavailable' }));

test('shows a labelled translated summary and preserves the original transcript and audio', async () => {
  api.get.mockImplementation((path) => path.endsWith('/audio') ? Promise.resolve({ data: new Blob(['original']) }) : Promise.resolve({ data: { summary: 'अम्मा ने खाना खाया।', summary_language: 'hi' } }));
  URL.createObjectURL = jest.fn(() => 'blob:original');
  URL.revokeObjectURL = jest.fn();
  render(<VoiceReply reply={{ id: 'voice-1', transcription: 'Original Telugu transcript' }} />);
  expect(await screen.findByText('अम्मा ने खाना खाया।')).toBeInTheDocument();
  expect(screen.getByText('Original Telugu transcript')).toBeInTheDocument();
  fireEvent.click(screen.getByText('Play voice note'));
  expect(await screen.findByTestId('voice-player-voice-1')).toHaveAttribute('src', 'blob:original');
});

test('summary failure does not remove the original recording controls', async () => {
  api.get.mockRejectedValue(new Error('unavailable'));
  render(<VoiceReply reply={{ id: 'voice-2', transcription: 'Original transcript' }} />);
  expect(screen.getByText('Play voice note')).toBeInTheDocument();
  expect(screen.getByText('Original transcript')).toBeInTheDocument();
});
