import 'dart:convert';
import 'dart:developer';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'user_profile.dart';

/// Local persistence of the user questionnaire (one JSON file).
abstract class ProfileStore {
  /// Persists [profile], overwriting the previous one.
  Future<void> save(UserProfile profile);

  /// Returns the stored profile, or an empty one when absent/unreadable.
  Future<UserProfile> load();
}

/// File-backed [ProfileStore] writing `<baseDir>/profile.json`.
///
/// In production [baseDir] is `null` and resolves lazily to
/// `getApplicationDocumentsDirectory()/kali_profile/`. Unit tests inject a
/// temp [Directory] so no native `path_provider` channel is touched.
class FileProfileStore implements ProfileStore {
  FileProfileStore({Directory? baseDir}) : _baseDir = baseDir;

  Directory? _baseDir;

  Future<Directory> _dir() async {
    var dir = _baseDir;
    if (dir == null) {
      final docs = await getApplicationDocumentsDirectory();
      dir = Directory('${docs.path}/kali_profile');
      _baseDir = dir;
    }
    if (!await dir.exists()) {
      await dir.create(recursive: true);
    }
    return dir;
  }

  @override
  Future<void> save(UserProfile profile) async {
    final dir = await _dir();
    // Atomic write: serialize to a sibling `.tmp` then rename over the target,
    // so an interrupted write can never leave a half-written profile.json.
    final target = File('${dir.path}/profile.json');
    final tmp = File('${target.path}.tmp');
    await tmp.writeAsString(jsonEncode(profile.toJson()));
    await tmp.rename(target.path);
  }

  @override
  Future<UserProfile> load() async {
    // The profile is optional garnish on the system prompt: ANY failure here
    // (corrupt JSON, I/O error, missing path_provider plugin in tests) must
    // degrade to an empty profile, never break the chat.
    try {
      final dir = await _dir();
      final file = File('${dir.path}/profile.json');
      if (!await file.exists()) return const UserProfile();
      final json = jsonDecode(await file.readAsString()) as Map<String, dynamic>;
      return UserProfile.fromJson(json);
    } on Object catch (e, st) {
      log('profile load failed, using empty profile',
          name: 'ProfileStore', error: e, stackTrace: st);
      return const UserProfile();
    }
  }
}
