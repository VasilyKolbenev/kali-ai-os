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
    final m = RegExp(r'\*/(\d+)').firstMatch(sched['cron'] as String);
    if (m != null) interval = int.parse(m.group(1)!) / 60;
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
