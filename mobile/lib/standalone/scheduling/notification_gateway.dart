import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:timezone/timezone.dart' as tz;

import 'notification_ids.dart';

/// A registered (or cancelled) local notification, abstracted so the scheduler
/// is testable without the native channel.
abstract class NotificationGateway {
  /// Requests OS notification permission; returns whether it is granted.
  Future<bool> requestPermission();

  /// Schedules a single notification with [id] to fire at [when].
  Future<void> scheduleAt(int id, DateTime when, String title, String body);

  /// Cancels the whole 256-id block for [agentName].
  Future<void> cancelForAgent(String agentName);

  /// Number of notifications currently pending with the OS.
  Future<int> pendingCount();
}

/// Native [NotificationGateway] over `flutter_local_notifications` + `timezone`.
///
/// Not unit-tested (native channel); validated in the live device test. The
/// scheduler is exercised against [NotificationGateway] via a fake double.
class LocalNotificationGateway implements NotificationGateway {
  /// Wraps an already-initialized [FlutterLocalNotificationsPlugin].
  LocalNotificationGateway(this._plugin);

  final FlutterLocalNotificationsPlugin _plugin;

  static const NotificationDetails _details = NotificationDetails(
    android: AndroidNotificationDetails(
      'kali_reminders',
      'Напоминания',
      importance: Importance.high,
      priority: Priority.high,
    ),
    iOS: DarwinNotificationDetails(),
  );

  @override
  Future<bool> requestPermission() async {
    final bool? ios = await _plugin
        .resolvePlatformSpecificImplementation<
            IOSFlutterLocalNotificationsPlugin>()
        ?.requestPermissions(alert: true, badge: true, sound: true);
    final bool? android = await _plugin
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.requestNotificationsPermission();
    return ios ?? android ?? true;
  }

  @override
  Future<void> scheduleAt(int id, DateTime when, String title, String body) =>
      _plugin.zonedSchedule(
        id: id,
        title: title,
        body: body,
        scheduledDate: tz.TZDateTime.from(when, tz.local),
        notificationDetails: _details,
        androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
      );

  @override
  Future<void> cancelForAgent(String name) async {
    final int base = blockBase(name);
    for (var i = 0; i < blockSlots; i++) {
      await _plugin.cancel(id: base + i);
    }
  }

  @override
  Future<int> pendingCount() async =>
      (await _plugin.pendingNotificationRequests()).length;
}
