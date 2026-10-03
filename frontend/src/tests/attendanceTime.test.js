import { describe, expect, it } from 'vitest';
import { minutes, workedPreview } from '../pages/Attendance';

/**
 * The form shows a worked-time figure before the record is saved, and it has to
 * agree with what the API will compute - otherwise the number on screen and the
 * number in payroll are different numbers, and the one that matters is the one
 * nobody checked.
 *
 * The server rule being mirrored: minutes between check-in and check-out, plus
 * a day when the shift crosses midnight or the check-out is earlier than the
 * check-in. Below zero is not a duration.
 */
describe('minutes', () => {
  it('converts a clock time to minutes past midnight', () => {
    expect(minutes('09:00')).toBe(540);
    expect(minutes('00:00')).toBe(0);
    expect(minutes('23:59')).toBe(1439);
  });

  it('returns null for a blank or unparseable value', () => {
    expect(minutes('')).toBeNull();
    expect(minutes(null)).toBeNull();
    expect(minutes(undefined)).toBeNull();
    expect(minutes('half nine')).toBeNull();
  });
});

describe('workedPreview', () => {
  it('reports a normal day', () => {
    expect(workedPreview('09:00', '17:30', false)).toBe('8h 30m');
  });

  it('reports whole hours without a stray minutes part', () => {
    expect(workedPreview('09:00', '17:00', false)).toBe('8h');
  });

  it('carries an overnight shift into the next day', () => {
    expect(workedPreview('22:00', '06:00', false)).toBe('8h');
  });

  it('honours the explicit next-day flag even when the times look forward', () => {
    // 09:00 -> 17:00 with the flag set is what the server treats as ending the
    // following day. The preview must not quietly disagree with it.
    expect(workedPreview('09:00', '17:00', true)).toBe('32h');
  });

  it('is null until both times are known', () => {
    expect(workedPreview('09:00', '', false)).toBeNull();
    expect(workedPreview('', '17:00', false)).toBeNull();
    expect(workedPreview('', '', false)).toBeNull();
  });

  it('renders a zero-length span as 0h, matching what the API reports', () => {
    // The server returns 0 minutes for check_in == check_out, so the preview
    // showing "—" would put two different numbers on screen for one record.
    expect(workedPreview('09:00', '09:00', false)).toBe('0h');
  });
});