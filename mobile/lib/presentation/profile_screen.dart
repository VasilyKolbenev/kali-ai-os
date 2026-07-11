import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/l10n.dart';
import '../core/theme.dart';
import '../standalone/user_profile.dart';
import 'standalone_chat_screen.dart' show profileStoreProvider;

const _ageRanges = ['18-25', '26-35', '36-45', '46-55', '55+'];

/// Editable questionnaire («анкета») for the standalone mode: name, gender,
/// occupation, city, age. Saved locally; the standalone chat prepends it to
/// every agent's system prompt so Jarvis addresses the user properly.
class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key});

  @override
  ConsumerState<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends ConsumerState<ProfileScreen> {
  final TextEditingController _nameController = TextEditingController();
  final TextEditingController _occupationController = TextEditingController();
  final TextEditingController _cityController = TextEditingController();
  String? _gender;
  String? _ageRange;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final profile = await ref.read(profileStoreProvider).load();
    if (!mounted) return;
    setState(() {
      _nameController.text = profile.name ?? '';
      _occupationController.text = profile.occupation ?? '';
      _cityController.text = profile.city ?? '';
      _gender = profile.gender;
      _ageRange = profile.ageRange;
      _loading = false;
    });
  }

  @override
  void dispose() {
    _nameController.dispose();
    _occupationController.dispose();
    _cityController.dispose();
    super.dispose();
  }

  String? _valueOrNull(TextEditingController c) {
    final v = c.text.trim();
    return v.isEmpty ? null : v;
  }

  Future<void> _save() async {
    final t = L10n.of(ref);
    await ref.read(profileStoreProvider).save(UserProfile(
          name: _valueOrNull(_nameController),
          gender: _gender,
          occupation: _valueOrNull(_occupationController),
          city: _valueOrNull(_cityController),
          ageRange: _ageRange,
        ));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(t.profileSaved)),
    );
  }

  Widget _label(String text) => Padding(
        padding: const EdgeInsets.only(bottom: 8, top: 16),
        child: Text(
          text,
          style: Theme.of(context)
              .textTheme
              .bodyMedium
              ?.copyWith(color: AppTheme.textSecondary),
        ),
      );

  Widget _textField(Key key, TextEditingController controller) => TextField(
        key: key,
        controller: controller,
        autocorrect: false,
        decoration: InputDecoration(
          filled: true,
          fillColor: AppTheme.glassSurface,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: BorderSide.none,
          ),
        ),
        style: const TextStyle(color: Colors.white),
      );

  @override
  Widget build(BuildContext context) {
    final t = L10n.of(ref);

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: Text(
          t.profileTitle.toUpperCase(),
          style: Theme.of(context)
              .textTheme
              .displayMedium
              ?.copyWith(fontSize: 16, letterSpacing: 3),
        ),
        backgroundColor: Colors.transparent,
        centerTitle: true,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: AppTheme.primary))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text(
                  t.profileHelper,
                  style: const TextStyle(
                      color: AppTheme.textSecondary, fontSize: 12, height: 1.4),
                ),
                _label(t.profileName),
                _textField(const Key('profile-name'), _nameController),
                _label(t.profileGender),
                Wrap(
                  spacing: 8,
                  children: [
                    ChoiceChip(
                      label: Text(t.genderMale),
                      selected: _gender == 'male',
                      onSelected: (sel) =>
                          setState(() => _gender = sel ? 'male' : null),
                    ),
                    ChoiceChip(
                      label: Text(t.genderFemale),
                      selected: _gender == 'female',
                      onSelected: (sel) =>
                          setState(() => _gender = sel ? 'female' : null),
                    ),
                  ],
                ),
                _label(t.profileOccupation),
                _textField(const Key('profile-occupation'), _occupationController),
                _label(t.profileCity),
                _textField(const Key('profile-city'), _cityController),
                _label(t.profileAge),
                Wrap(
                  spacing: 8,
                  children: _ageRanges
                      .map((range) => ChoiceChip(
                            label: Text(range),
                            selected: _ageRange == range,
                            onSelected: (sel) =>
                                setState(() => _ageRange = sel ? range : null),
                          ))
                      .toList(),
                ),
                const SizedBox(height: 32),
                SizedBox(
                  width: double.infinity,
                  height: 52,
                  child: ElevatedButton(
                    key: const Key('profile-save'),
                    onPressed: _save,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTheme.primary,
                      foregroundColor: Colors.black,
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(16)),
                    ),
                    child: Text(t.save,
                        style: const TextStyle(
                            fontWeight: FontWeight.bold, fontSize: 16)),
                  ),
                ),
              ],
            ),
    );
  }
}
