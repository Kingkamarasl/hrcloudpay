import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock('../api/client', () => ({
  api: { get },
  downloadFile: vi.fn(),
}));

import EmployeeDashboard from '../pages/EmployeeDashboard';

describe('EmployeeDashboard', () => {
  beforeEach(() => {
    get.mockReset();
    get.mockImplementation((path) => {
      const responses = {
        '/employees/employees/my-profile/': { full_name: 'Ada Lovelace', job_title: 'Engineer' },
        '/payroll/payslips/': { results: [] },
        '/attendance/records/': { results: [] },
        '/leave/requests/': { results: [] },
      };
      return Promise.resolve(responses[path]);
    });
  });

  it('loads only employee-scoped collections', async () => {
    render(<MemoryRouter><EmployeeDashboard /></MemoryRouter>);

    await waitFor(() => expect(screen.getByText('Welcome, Ada Lovelace.')).toBeInTheDocument());

    expect(get.mock.calls.map(([path]) => path)).toEqual([
      '/employees/employees/my-profile/',
      '/payroll/payslips/',
      '/attendance/records/',
      '/leave/requests/',
    ]);
    expect(get.mock.calls.map(([path]) => path)).not.toEqual(expect.arrayContaining([
      '/employees/employees/',
      '/payroll/runs/',
      '/integrations/',
      '/regional/compliance-dashboard/',
    ]));
  });
});
