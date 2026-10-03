/**
 * Money formatting for payslips and compensation figures.
 *
 * Two rules this enforces, both of which used to be violated:
 *
 * 1. DRF serialises `Decimal` as a *string*, so payslip amounts arrive as
 *    "850.00" while locally-computed totals are numbers. Both must render the
 *    same, or a payslip shows one figure from the API and a differently
 *    punctuated one from a `reduce()` a few lines above it.
 *
 * 2. It must never render "NaN". A payslip is a document an employee disputes
 *    and a company files; "NaN" in the Net column is worse than a wrong-looking
 *    zero, because it makes the whole row untrustworthy. Anything unparseable
 *    becomes 0.00 and the row still reads as a figure rather than as an error.
 *
 * Currency is deliberately *not* included. Callers render the code from the
 * employee's company config separately, so a formatted value is never bound to
 * the wrong symbol when a company changes currency.
 */

/** Parse a DRF money value (string, number, or nullish) to a finite number. */
export function toAmount(value: unknown): number {
  if (value === null || value === undefined || value === '') return 0;
  const parsed = typeof value === 'number' ? value : Number(value);
  // Number('abc') and Number(Infinity) both fail here. NaN from arithmetic
  // (0/0, "x" - 1) lands here too, which is the case this exists for.
  return Number.isFinite(parsed) ? parsed : 0;
}

/**
 * Format an amount with thousands separators and exactly two decimals.
 *
 * `undefined` means the browser's locale, matching the behaviour the page had
 * before this was extracted.
 */
export function money(value: unknown): string {
  return toAmount(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/**
 * Sum payslip money across rows without letting a bad row poison the total.
 *
 * Used by the payroll totals, which reduce over `gross_salary`, `tax_amount` and
 * `net_salary` from every visible payslip. A single malformed row previously
 * made the entire total NaN.
 */
export function sumMoney(rows: Array<Record<string, unknown>>, keys: string[]): number {
  return keys.reduce(
    (total, key) => total + rows.reduce((sum, row) => sum + toAmount(row?.[key]), 0),
    0,
  );
}