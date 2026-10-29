import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock('../api/client', () => ({
  api: { get, post },
}));

import Billing from '../pages/Billing';

describe('Billing', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    post.mockResolvedValue({});
    get.mockImplementation((path) => {
      const responses = {
        '/auth/billing/': {
          state: { status: 'active', allowed: true, reason: '' },
          available_providers: [{ provider: 'paypal', name: 'PayPal (card or PayPal)' }],
          default_checkout_provider: 'paypal',
          subscription: {
            plan: 'business', status: 'active', provider: 'paypal',
            billing_cycle: 'monthly', monthly_price: '49.00', currency: 'USD',
            renews_at: '2030-06-30T00:00:00Z', cancel_at_period_end: true,
          },
        },
        '/auth/billing/plans/': [{
          id: 'business', name: 'Business', monthly_price: '49.00',
          annual_price: '490.00', employee_limit: 100, user_limit: 10,
        }],
        '/auth/billing/invoices/': [],
      };
      return Promise.resolve(responses[path]);
    });
  });

  it('explains that a PayPal cancellation pauses renewal and can be resumed', async () => {
    render(<MemoryRouter initialEntries={['/billing']}><Billing /></MemoryRouter>);

    await waitFor(() => expect(screen.getByText('Recurring billing paused')).toBeInTheDocument());

    expect(screen.getAllByRole('button', { name: 'Resume recurring billing' })).toHaveLength(2);
    expect(screen.getByText(/PayPal renewals are paused/i)).toBeInTheDocument();
  });
});
