import 'reminder_config.dart';

/// PURE. Next fire DateTimes (naive local wall-clock) for a reminder, starting
/// at/after [from], within the daily [startHour, endHour) window, every
/// `intervalHours`, up to [maxCount] and not past [horizonEnd]. `from` is the
/// only "now" — fully deterministic. DST is resolved later by the gateway.
List<DateTime> nextFireTimes({
  required ReminderConfig config,
  required DateTime from,
  required DateTime horizonEnd,
  required int maxCount,
}) {
  final out = <DateTime>[];
  if (maxCount <= 0) return out;
  final stepMs = (config.intervalHours * 3600 * 1000).round();
  if (stepMs <= 0) return out;

  var day = DateTime(from.year, from.month, from.day);
  while (!day.isAfter(horizonEnd)) {
    final dayEnd = DateTime(day.year, day.month, day.day, config.endHour);
    var t = DateTime(day.year, day.month, day.day, config.startHour);
    while (t.isBefore(dayEnd)) {
      if (!t.isBefore(horizonEnd)) return out; // horizonEnd is exclusive
      if (!t.isBefore(from)) {
        out.add(t);
        if (out.length >= maxCount) return out;
      }
      t = t.add(Duration(milliseconds: stepMs));
    }
    day = day.add(const Duration(days: 1));
  }
  return out;
}
