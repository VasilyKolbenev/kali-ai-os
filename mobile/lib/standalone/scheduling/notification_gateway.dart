import 'dart:io' show Platform;

import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:timezone/timezone.dart' as tz;

import 'notification_ids.dart';

/// The Android channel id reminders are posted on (also referenced by
/// [LocalNotificationGateway._details]).
const String kReminderChannelId = 'kali_reminders';

/// Initializes the shared notification plugin and creates the reminder channel.
///
/// Must be called once at startup, before any [LocalNotificationGateway]
/// schedules — otherwise `zonedSchedule` no-ops on a real device and reminders
/// never fire (a gap unit tests with a fake gateway cannot see). Idempotent:
/// `FlutterLocalNotificationsPlugin()` is a singleton, so re-calling is safe.
Future<void> initializeNotifications() async {
  final plugin = FlutterLocalNotificationsPlugin();
  await plugin.initialize(
    settings: const InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      // Permission is requested explicitly via requestPermission(), not here.
      iOS: DarwinInitializationSettings(
        requestAlertPermission: false,
        requestBadgePermission: false,
        requestSoundPermission: false,
      ),
    ),
  );
  // Android 8+ requires an explicit channel before posting to it.
  await plugin
      .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin>()
      ?.createNotificationChannel(
    const AndroidNotificationChannel(
      kReminderChannelId,
      'Напоминания',
      description: 'Напоминания от ваших агентов',
      importance: Importance.high,
    ),
  );
}

/// Reduces the per-platform permission results into a single granted flag.
///
/// On Android an *indeterminate* result (null resolver / null answer) must NOT
/// be reported as granted: defaulting unknown→true on Android hides a silent
/// no-fire, so we surface it as denied and let the UI show the
/// 'permission needed' affordance. iOS keeps its existing `ios ?? true` path
/// (the iOS resolver answers reliably; null there means "not iOS").
///
/// [isAndroid] is injected so the reducer is unit-testable off-device.
bool resolvePermissionGranted({
  required bool? ios,
  required bool? android,
  required bool isAndroid,
}) {
  if (isAndroid) return android ?? false;
  return ios ?? android ?? true;
}

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
  /// Wraps the shared [FlutterLocalNotificationsPlugin]. The plugin must have
  /// been initialized via [initializeNotifications] at startup.
  LocalNotificationGateway(this._plugin);

  final FlutterLocalNotificationsPlugin _plugin;

  static const NotificationDetails _details = NotificationDetails(
    android: AndroidNotificationDetails(
      kReminderChannelId,
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
    return resolvePermissionGranted(
      ios: ios,
      android: android,
      isAndroid: Platform.isAndroid,
    );
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
