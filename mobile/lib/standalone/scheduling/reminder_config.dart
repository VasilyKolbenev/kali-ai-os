import 'ru_interval_parse.dart';

/// Validated reminder configuration parsed from a voice-built skill.yaml.
class ReminderConfig {
  const ReminderConfig({
    required this.message,
    required this.intervalHours,
    required this.startHour,
    required this.endHour,
  });

  final String message;
  final double intervalHours; // [0.25, 24]
  final int startHour;        // [0, 23]
  final int endHour;          // [startHour+1, 24]
}

double? _toDouble(Object? v) =>
    v is num ? v.toDouble() : (v is String ? double.tryParse(v) : null);

/// Field-aware 5-field cron → interval in hours; null if unrecognized.
///
/// `*/N * * * *`  → every N minutes (N/60 hours).
/// `0 */M * * *`  → every M hours (minute fixed, hour steps).
/// Anything else recognized loosely returns null so the caller keeps its
/// 1h default rather than mis-dividing the first `*/N` by 60.
double? _cronIntervalHours(String cron) {
  final fields = cron.trim().split(RegExp(r'\s+'));
  if (fields.length < 2) return null;
  final minute = fields[0];
  final hour = fields[1];
  final minStep = RegExp(r'^\*/(\d+)$').firstMatch(minute);
  if (minStep != null) return int.parse(minStep.group(1)!) / 60;
  final hourStep = RegExp(r'^\*/(\d+)$').firstMatch(hour);
  final minuteFixed = minute == '0' || RegExp(r'^\d+$').hasMatch(minute);
  if (hourStep != null && minuteFixed) return int.parse(hourStep.group(1)!).toDouble();
  return null;
}

/// Parse the nested wizard config a voice-built reminder carries.
/// Precedence: reminders.interval_hours → free-text `interval` → schedule.cron
/// `*/N` → default 1h. Window from `time_window` free-text or 8..22.
/// [fallbackMessage] (the agent description) is the only message source —
/// the wizard captures none.
ReminderConfig parseReminderConfig(
  Map<dynamic, dynamic> config, {
  required String fallbackMessage,
}) {
  double interval = 1;
  final rem = config['reminders'];
  final sched = config['schedule'];
  if (rem is Map && rem['interval_hours'] != null) {
    interval = _toDouble(rem['interval_hours']) ?? 1;
  } else if (config['interval'] is String) {
    final mins = parseIntervalMinutes(config['interval'] as String);
    final hrs = parseIntervalHours(config['interval'] as String);
    if (mins != null) {
      interval = mins / 60;
    } else if (hrs != null) {
      interval = hrs.toDouble();
    }
  } else if (sched is Map && sched['cron'] is String) {
    final parsed = _cronIntervalHours(sched['cron'] as String);
    if (parsed != null) interval = parsed;
  }
  interval = interval.clamp(0.25, 24).toDouble(); // num.clamp -> num; keep double

  int start = 8, end = 22;
  if (config['time_window'] is String) {
    final w = parseTimeWindow(config['time_window'] as String);
    if (w != null) {
      start = w.$1;
      end = w.$2;
    }
  }
  start = start.clamp(0, 23);
  if (end <= start) end = start + 1;
  end = end.clamp(start + 1, 24);

  var msg = fallbackMessage.trim();
  if (msg.isEmpty) msg = 'Напоминание';
  return ReminderConfig(
    message: msg,
    intervalHours: interval,
    startHour: start,
    endHour: end,
  );
}
