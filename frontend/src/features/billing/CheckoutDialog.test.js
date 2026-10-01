import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { CheckoutDialog } from './CheckoutDialog';

jest.mock('@/context/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u-123', name: 'Gunak Tester', email: 'gunak@example.com', phone: '+919876543210' },
  }),
}));

const mockGet = jest.fn();
const mockPost = jest.fn();

jest.mock('@/lib/api', () => ({
  api: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
  },
  formatAxiosError: (e) => e?.message || 'Error',
}));

jest.mock('./razorpayCheckout', () => ({
  checkoutKey: () => 'idemp-key',
  loadCheckout: jest.fn().mockResolvedValue(true),
  openCheckout: jest.fn().mockResolvedValue({ status: 'paid' }),
  openSubscriptionModal: jest.fn().mockResolvedValue({ status: 'authenticated' }),
}));

import { openSubscriptionModal } from './razorpayCheckout';

describe('CheckoutDialog - 7-Day Trial & Live Integration', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    openSubscriptionModal.mockResolvedValue({ status: 'authenticated' });
    mockGet.mockImplementation((url) => {
      if (url === '/payment/config') {
        return Promise.resolve({
          data: {
            provider: 'razorpay',
            enabled: true,
            key_id: 'rzp_live_testkey',
            test_mode: false,
            currencies: ['INR', 'USD'],
            auto_renews: true,
            checkout_script: 'https://checkout.razorpay.com/v1/checkout.js',
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    mockPost.mockImplementation((url, body) => {
      if (url === '/payment/quote') {
        return Promise.resolve({
          data: {
            plan: 'bandham',
            plan_name: 'AYANA Bandham',
            billing: 'month',
            currency: 'INR',
            subtotal: 179900,
            discount: 0,
            credit: 0,
            amount: 179900,
            lifetime: false,
            coupon_id: null,
            terms: 'Monthly care plan.',
          },
        });
      }
      if (url === '/subscribe') {
        return Promise.resolve({
          data: {
            local_subscription_id: 'sub-local-1',
            subscription_id: 'sub_rzp_123',
            key_id: 'rzp_live_testkey',
            plan: 'bandham',
            billing: 'month',
            currency: 'INR',
            amount: 179900,
            status: 'created',
            trial: true,
            trial_ends_at: '2026-10-08T00:00:00Z',
          },
        });
      }
      return Promise.resolve({ data: {} });
    });
  });

  it('does NOT render test mode banner', async () => {
    render(
      <CheckoutDialog
        selection={{ plan: 'bandham', billing: 'month', currency: 'INR' }}
        allowTrial={true}
        onClose={jest.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('checkout-title')).toBeInTheDocument();
    });

    expect(screen.queryByTestId('checkout-test-mode')).not.toBeInTheDocument();
    expect(screen.queryByText(/Razorpay test mode/i)).not.toBeInTheDocument();
  });

  it('does NOT render "Continue with a 7-day trial — no card"', async () => {
    render(
      <CheckoutDialog
        selection={{ plan: 'bandham', billing: 'month', currency: 'INR' }}
        allowTrial={true}
        onClose={jest.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('checkout-title')).toBeInTheDocument();
    });

    expect(screen.queryByTestId('checkout-start-trial')).not.toBeInTheDocument();
    expect(screen.queryByText(/no card/i)).not.toBeInTheDocument();
  });

  it('renders 7-day trial flow with ₹0 today and auto-deduction notice', async () => {
    render(
      <CheckoutDialog
        selection={{ plan: 'bandham', billing: 'month', currency: 'INR' }}
        allowTrial={true}
        onClose={jest.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('checkout-pay-button')).toBeInTheDocument();
    });

    // Check trial button label
    expect(screen.getByTestId('checkout-pay-button')).toHaveTextContent(/Start 7-day free trial with Razorpay/i);

    // Check Total today is ₹0
    expect(screen.getByTestId('checkout-total')).toHaveTextContent(/₹0\.00|0/);

    // Check first auto-deduction copy is displayed
    expect(screen.getByText(/First auto-deduction/i)).toBeInTheDocument();
  });

  it('starts subscription with card details on click', async () => {
    const onComplete = jest.fn();
    render(
      <CheckoutDialog
        selection={{ plan: 'bandham', billing: 'month', currency: 'INR' }}
        allowTrial={true}
        onClose={jest.fn()}
        onComplete={onComplete}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('checkout-quote')).toBeInTheDocument();
      expect(screen.getByTestId('checkout-pay-button')).not.toBeDisabled();
    });

    fireEvent.click(screen.getByTestId('checkout-pay-button'));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/subscribe',
        expect.objectContaining({
          plan: 'bandham',
          billing: 'month',
          currency: 'INR',
          trial: true,
        })
      );
      expect(openSubscriptionModal).toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(onComplete).toHaveBeenCalled();
    });
  });
});
