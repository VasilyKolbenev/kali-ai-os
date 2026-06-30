/// Russian number words for spelled-out intervals (STT often writes words).
const Map<String, int> _ruNum = {
  'один': 1, 'одну': 1, 'два': 2, 'две': 2, 'три': 3, 'четыре': 4,
  'пять': 5, 'шесть': 6, 'семь': 7, 'восемь': 8, 'девять': 9,
  'десять': 10, 'двенадцать': 12,
};

/// 'каждые 2 часа' / 'каждый час' / 'ежечасно' → hours; null if none.
int? parseIntervalHours(String text) {
  final t = text.toLowerCase();
  final m = RegExp(r'(\d+)\s*час').firstMatch(t);
  if (m != null) return int.parse(m.group(1)!).clamp(1, 1 << 30);
  for (final e in _ruNum.entries) {
    // \\b doesn't work for Cyrillic in Dart (ASCII-only word chars);
    // use space-or-start anchor instead.
    if (RegExp('(^|\\s)${e.key}\\s+час').hasMatch(t)) return e.value;
  }
  if (t.contains('час') || t.contains('ежечас')) return 1;
  return null;
}

/// 'каждые 30 минут' / 'полчаса' → minutes; null if none.
int? parseIntervalMinutes(String text) {
  final t = text.toLowerCase();
  final m = RegExp(r'(\d+)\s*мин').firstMatch(t);
  if (m != null) return int.parse(m.group(1)!);
  if (t.contains('пол') && t.contains('час')) return 30;
  return null;
}

/// Best-effort window parse: first two hour numbers (≤24); a "вечера" phrasing
/// shifts a single-digit end into PM. Returns (start, end) or null.
(int, int)? parseTimeWindow(String text) {
  final t = text.toLowerCase();
  final nums = RegExp(r'\d{1,2}')
      .allMatches(t)
      .map((m) => int.parse(m.group(0)!))
      .where((n) => n <= 24)
      .toList();
  if (nums.length < 2) return null;
  var s = nums[0];
  var e = nums[1];
  if (t.contains('вечера') && e < 12) e += 12;
  if (s < 0 || s > 23 || e <= s || e > 24) return null;
  return (s, e);
}
