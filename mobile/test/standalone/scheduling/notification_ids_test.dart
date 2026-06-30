import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/scheduling/notification_ids.dart';

void main() {
  test('block base is stable and within int32', () {
    final b = blockBase('water');
    expect(b, blockBase('water'));        // stable
    expect(b, lessThan(1 << 31));         // int32-safe
    expect(b & 0xFF, 0);                  // 256-aligned block
  });
  test('slot ids stay inside the agent block', () {
    final b = blockBase('water');
    expect(slotId('water', 0), b);
    expect(slotId('water', 255), b + 255);
    expect(blockSlots, 256);
  });
}
