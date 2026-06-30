// Unit tests for the permission-reduction seam of the notification gateway.
//
// The native LocalNotificationGateway can't be exercised off-device, so the
// reduction of the two per-platform permission answers into one granted flag is
// extracted into the pure resolvePermissionGranted() and tested here.

import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/scheduling/notification_gateway.dart';

void main() {
  group('resolvePermissionGranted on Android', () {
    test('indeterminate (null android result) is NOT granted', () {
      // The real bug: a null resolver/answer used to fall through to `true`,
      // hiding a silent no-fire. On Android unknown must surface as denied so
      // the 'permission needed' affordance shows.
      expect(
        resolvePermissionGranted(ios: null, android: null, isAndroid: true),
        false,
      );
    });

    test('explicit android grant is honoured', () {
      expect(
        resolvePermissionGranted(ios: null, android: true, isAndroid: true),
        true,
      );
    });

    test('explicit android denial is honoured', () {
      expect(
        resolvePermissionGranted(ios: null, android: false, isAndroid: true),
        false,
      );
    });

    test('a stray ios answer does not leak into the Android decision', () {
      expect(
        resolvePermissionGranted(ios: true, android: null, isAndroid: true),
        false,
      );
    });
  });

  group('resolvePermissionGranted on iOS', () {
    test('ios grant wins', () {
      expect(
        resolvePermissionGranted(ios: true, android: null, isAndroid: false),
        true,
      );
    });

    test('ios denial wins', () {
      expect(
        resolvePermissionGranted(ios: false, android: null, isAndroid: false),
        false,
      );
    });

    test('unknown (both null, not Android) keeps the optimistic default', () {
      expect(
        resolvePermissionGranted(ios: null, android: null, isAndroid: false),
        true,
      );
    });
  });
}
