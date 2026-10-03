import { describe, it, expect } from 'vitest';
import { money, toAmount, sumMoney } from '../utils/money';

describe('toAmount', () => {
  it('parses DRF decimal strings', () => {
    // DRF serialises Decimal as a string. This is the common case, not an edge.
    expect(toAmount('850.00')).toBe(850);
    expect(toAmount('1234567.89')).toBe(1234567.89);
  });

  it('passes numbers through', () => {
    expect(toAmount(850)).toBe(850);
    expect(toAmount(0)).toBe(0);
  });

  it('treats nullish and empty as zero', () => {
    expect(toAmount(null)).toBe(0);
    expect(toAmount(undefined)).toBe(0);
    expect(toAmount('')).toBe(0);
  });

  it('never returns NaN', () => {
    // The reason this helper exists. A payslip must not render "NaN".
    expect(toAmount('abc')).toBe(0);
    expect(toAmount(NaN)).toBe(0);
    expect(toAmount(Infinity)).toBe(0);
    expect(toAmount(-Infinity)).toBe(0);
    expect(toAmount({})).toBe(0);
  });

  it('preserves negatives', () => {
    // A clawback or a refund is a real payslip case; the sign must survive.
    expect(toAmount('-250.50')).toBe(-250.5);
  });
});

describe('money', () => {
  it('always renders two decimals', () => {
    expect(money(1000)).toBe('1,000.00');
    expect(money('1000')).toBe('1,000.00');
    expect(money(0)).toBe('0.00');
  });

  it('renders zero for missing values rather than NaN', () => {
    expect(money(null)).toBe('0.00');
    expect(money(undefined)).toBe('0.00');
  });

  it('never renders NaN for malformed input', () => {
    expect(money('not-a-number')).toBe('0.00');
    expect(money(NaN)).toBe('0.00');
  });

  it('keeps the sign on negative amounts', () => {
    expect(money(-250.5)).toBe('-250.50');
  });

  it('formats a string and its numeric equivalent identically', () => {
    // The API row and the locally-computed total must not disagree because one
    // arrived as a string and the other as a number.
    expect(money('2000.00')).toBe(money(2000));
  });
});

describe('sumMoney', () => {
  it('sums the requested keys across rows', () => {
    const rows = [
      { gross_salary: '1000.00', tax_amount: '100.00' },
      { gross_salary: '2000.00', tax_amount: '300.00' },
    ];
    expect(sumMoney(rows, ['gross_salary'])).toBe(3000);
    expect(sumMoney(rows, ['tax_amount'])).toBe(400);
  });

  it('skips missing keys as zero', () => {
    expect(sumMoney([{ net_salary: '100' }, {}], ['net_salary'])).toBe(100);
  });

  it('is not poisoned by one malformed row', () => {
    // Before sumMoney, a single bad row made the whole total NaN.
    const rows = [
      { net_salary: '1000.00' },
      { net_salary: 'oops' },
      { net_salary: '2000.00' },
    ];
    expect(sumMoney(rows, ['net_salary'])).toBe(3000);
  });

  it('returns zero for an empty row set', () => {
    expect(sumMoney([], ['net_salary'])).toBe(0);
  });
});