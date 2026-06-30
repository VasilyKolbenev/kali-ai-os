import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/scheduling/reminder_config.dart';
import 'package:kali_mobile/standalone/scheduling/reminder_schedule.dart';

ReminderConfig cfg({double interval = 2, int start = 8, int end = 22}) =>
    ReminderConfig(message: 'm', intervalHours: interval, startHour: start, endHour: end);

void main() {
  test('fires at start then every interval within window', () {
    final from = DateTime(2026, 6, 30, 7); // before window
    final t = nextFireTimes(config: cfg(), from: from, horizonEnd: DateTime(2026, 6, 30, 23), maxCount: 100);
    expect(t.map((d) => d.hour), [8, 10, 12, 14, 16, 18, 20]); // stops before 22
  });
  test('skips times before `from`', () {
    final from = DateTime(2026, 6, 30, 13);
    final t = nextFireTimes(config: cfg(), from: from, horizonEnd: DateTime(2026, 6, 30, 23), maxCount: 100);
    expect(t.first.hour, 14);
  });
  test('rolls into the next day', () {
    final from = DateTime(2026, 6, 30, 21);
    final t = nextFireTimes(config: cfg(), from: from, horizonEnd: DateTime(2026, 7, 1, 12), maxCount: 100);
    expect(t.map((d) => '${d.day}:${d.hour}'), ['1:8', '1:10']);
  });
  test('respects maxCount', () {
    final t = nextFireTimes(config: cfg(), from: DateTime(2026, 6, 30, 7), horizonEnd: DateTime(2026, 7, 10), maxCount: 3);
    expect(t.length, 3);
  });
  test('interval wider than window -> one per day', () {
    final t = nextFireTimes(config: cfg(interval: 20), from: DateTime(2026, 6, 30, 7), horizonEnd: DateTime(2026, 7, 2, 23), maxCount: 100);
    expect(t.map((d) => d.hour), everyElement(8));
    expect(t.length, 3);
  });
}
