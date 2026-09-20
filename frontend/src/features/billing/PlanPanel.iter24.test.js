import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { PlanPanel } from './PlanPanel';

jest.mock('@/lib/api', () => ({
  api: { get: jest.fn(() => Promise.resolve({ data: { lifetime: false } })) },
}));

jest.mock('./BillingStatus', () => ({ BillingStatus: () => <div data-testid="billing-status" /> }));
jest.mock('./SubscriptionStatus', () => ({ SubscriptionStatus: () => <div data-testid="subscription-status" /> }));
jest.mock('@/components/PricingCards', () => ({
  PricingCards: ({ onSelect }) => (
    <button data-testid="pricing-select" onClick={() => onSelect?.('raksha', 'year', 'USD')}>select</button>
  ),
}));
jest.mock('./CheckoutDialog', () => ({
  CheckoutDialog: ({ selection }) => selection ? <div data-testid="checkout-selection">{selection.currency}:{selection.billing}</div> : null,
}));
jest.mock('./SubscribeDialog', () => ({
  SubscribeDialog: ({ selection }) => selection ? <div data-testid="subscribe-selection">{selection.currency}:{selection.billing}</div> : null,
}));

describe('PlanPanel iteration24 coverage', () => {
  test('redeem free-access code forces pay-once mode and carries currency', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={client}>
        <PlanPanel
          plans={[{ id: 'raksha', name: 'Raksha', limits: { parents: 2, family_members: 2 } }]}
          currencies={[{ code: 'USD' }]}
          planId="raksha"
          plan={{ id: 'raksha', name: 'Raksha', limits: { parents: 2, family_members: 2 } }}
          usage={{ parents: 1, family_members_used: 0 }}
          circle={{ role: 'owner' }}
          reload={jest.fn()}
        />
      </QueryClientProvider>
    );

    expect(await screen.findByTestId('payment-mode-toggle')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('redeem-lifetime-code'));
    expect(screen.getByTestId('checkout-selection')).toHaveTextContent('USD:year');
    expect(screen.queryByTestId('subscribe-selection')).not.toBeInTheDocument();
  });
});
