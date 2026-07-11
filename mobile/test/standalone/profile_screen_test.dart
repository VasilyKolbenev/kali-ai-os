import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/presentation/profile_screen.dart';
import 'package:kali_mobile/presentation/standalone_chat_screen.dart'
    show profileStoreProvider;
import 'package:kali_mobile/standalone/profile_store.dart';
import 'package:kali_mobile/standalone/user_profile.dart';

class _FakeProfileStore implements ProfileStore {
  _FakeProfileStore([this.profile = const UserProfile()]);
  UserProfile profile;
  @override
  Future<UserProfile> load() async => profile;
  @override
  Future<void> save(UserProfile p) async => profile = p;
}

Widget _wrap(_FakeProfileStore store) => ProviderScope(
      overrides: [profileStoreProvider.overrideWithValue(store)],
      child: const MaterialApp(home: ProfileScreen()),
    );

void main() {
  testWidgets('prefills fields from the store', (tester) async {
    final store =
        _FakeProfileStore(const UserProfile(name: 'Вася', city: 'Ереван'));
    await tester.pumpWidget(_wrap(store));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(TextField, 'Вася'), findsOneWidget);
    expect(find.widgetWithText(TextField, 'Ереван'), findsOneWidget);
  });

  testWidgets('save persists edited fields', (tester) async {
    final store = _FakeProfileStore();
    await tester.pumpWidget(_wrap(store));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('profile-name')), 'Новый');
    // The ListView inflates children lazily — scroll the button into view.
    await tester.scrollUntilVisible(
      find.byKey(const Key('profile-save')),
      200,
      // TextFields carry their own Scrollable — target the ListView's one.
      scrollable: find
          .descendant(of: find.byType(ListView), matching: find.byType(Scrollable))
          .first,
    );
    await tester.tap(find.byKey(const Key('profile-save')));
    await tester.pumpAndSettle();
    expect(store.profile.name, 'Новый');
  });

  testWidgets('saving an emptied field clears it', (tester) async {
    final store = _FakeProfileStore(const UserProfile(name: 'Вася'));
    await tester.pumpWidget(_wrap(store));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('profile-name')), '');
    // The ListView inflates children lazily — scroll the button into view.
    await tester.scrollUntilVisible(
      find.byKey(const Key('profile-save')),
      200,
      // TextFields carry their own Scrollable — target the ListView's one.
      scrollable: find
          .descendant(of: find.byType(ListView), matching: find.byType(Scrollable))
          .first,
    );
    await tester.tap(find.byKey(const Key('profile-save')));
    await tester.pumpAndSettle();
    expect(store.profile.isEmpty, isTrue);
  });
}
