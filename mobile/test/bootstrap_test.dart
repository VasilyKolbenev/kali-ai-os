import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/main.dart';

void main() {
  test('bootstrap reaches runApp even when every side-effect throws', () async {
    Widget? mounted;
    await bootstrap(
      initTimezone: () async => throw Exception('tz'),
      initNotifications: () async => throw Exception('notif'),
      loadToken: () async => throw Exception('token'),
      runApp: (app) => mounted = app,
    );
    // Cold-start crash-safety: a throw in any pre-runApp side-effect must not
    // white-screen the app — runApp is still reached with the real app widget.
    expect(mounted, isA<KaliMobileApp>());
  });

  test('bootstrap runs the side-effects in order, then mounts', () async {
    final calls = <String>[];
    Widget? mounted;
    await bootstrap(
      initTimezone: () async => calls.add('tz'),
      initNotifications: () async => calls.add('notif'),
      loadToken: () async => calls.add('token'),
      runApp: (app) => mounted = app,
    );
    expect(calls, ['tz', 'notif', 'token']);
    expect(mounted, isA<KaliMobileApp>());
  });
}
