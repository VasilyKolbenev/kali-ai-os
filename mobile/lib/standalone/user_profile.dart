/// The user's optional questionnaire («анкета»): who Jarvis is talking to.
///
/// Immutable. All fields optional — an empty profile is valid and means the
/// standalone system prompt gets no profile block. [gender] holds the enum
/// value `male`/`female` (same contract as the desktop `/profile` API).
class UserProfile {
  const UserProfile({
    this.name,
    this.gender,
    this.occupation,
    this.city,
    this.ageRange,
  });

  final String? name;
  final String? gender;
  final String? occupation;
  final String? city;
  final String? ageRange;

  /// True when no field carries a value (null or blank).
  bool get isEmpty => [name, gender, occupation, city, ageRange]
      .every((v) => v == null || v.trim().isEmpty);

  Map<String, dynamic> toJson() => {
        'name': name,
        'gender': gender,
        'occupation': occupation,
        'city': city,
        'ageRange': ageRange,
      };

  /// Tolerant decode: non-string values become null instead of throwing —
  /// a hand-edited or stale file must never brick the profile.
  factory UserProfile.fromJson(Map<String, dynamic> json) {
    String? str(Object? v) => v is String && v.trim().isNotEmpty ? v : null;
    return UserProfile(
      name: str(json['name']),
      gender: str(json['gender']),
      occupation: str(json['occupation']),
      city: str(json['city']),
      ageRange: str(json['ageRange']),
    );
  }
}
