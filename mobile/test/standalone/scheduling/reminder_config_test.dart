import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/scheduling/reminder_config.dart';

void main() {
  test('reads nested reminders.interval_hours', () {
    final c = parseReminderConfig(
      {'reminders': {'enabled': true, 'interval_hours': 2}, 'time_window': 'с 8 до 22'},
      fallbackMessage: 'пить воду',
    );
    expect(c.intervalHours, 2);
    expect(c.startHour, 8);
    expect(c.endHour, 22);
    expect(c.message, 'пить воду');
  });
  test('falls back to free-text interval', () {
    final c = parseReminderConfig({'interval': 'каждые 3 часа'}, fallbackMessage: 'x');
    expect(c.intervalHours, 3);
  });
  test('sub-hour schedule.cron', () {
    final c = parseReminderConfig({'schedule': {'cron': '*/30 * * * *'}}, fallbackMessage: 'x');
    expect(c.intervalHours, closeTo(0.5, 1e-9));
  });
  test('hour-field cron parses as hours, not minutes', () {
    final c = parseReminderConfig({'schedule': {'cron': '0 */2 * * *'}}, fallbackMessage: 'x');
    expect(c.intervalHours, closeTo(2.0, 1e-9)); // not 0.25 (2/60 clamped)
  });
  test('unrecognized cron defaults to 1h', () {
    final c = parseReminderConfig({'schedule': {'cron': '5 4 * * *'}}, fallbackMessage: 'x');
    expect(c.intervalHours, 1);
  });
  test('defaults when nothing parses', () {
    final c = parseReminderConfig({'interval': 'абракадабра'}, fallbackMessage: '  ');
    expect(c.intervalHours, 1);
    expect(c.startHour, 8);
    expect(c.endHour, 22);
    expect(c.message, 'Напоминание'); // empty fallback -> default
  });
  test('clamps out-of-range', () {
    final c = parseReminderConfig(
      {'reminders': {'interval_hours': 999}, 'time_window': 'с 30 до 40'},
      fallbackMessage: 'x',
    );
    expect(c.intervalHours, 24);          // clamped
    expect(c.endHour, greaterThan(c.startHour));
  });
}
