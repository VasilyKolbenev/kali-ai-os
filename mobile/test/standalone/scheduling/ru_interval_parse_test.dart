import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/scheduling/ru_interval_parse.dart';

void main() {
  group('parseIntervalHours', () {
    test('digit form', () => expect(parseIntervalHours('каждые 2 часа'), 2));
    test('spelled-out', () => expect(parseIntervalHours('каждые два часа'), 2));
    test('every hour', () => expect(parseIntervalHours('каждый час'), 1));
    test('ежечасно', () => expect(parseIntervalHours('ежечасно'), 1));
    test('no hours -> null', () => expect(parseIntervalHours('по пятницам'), isNull));
  });
  group('parseIntervalMinutes', () {
    test('digit minutes', () => expect(parseIntervalMinutes('каждые 30 минут'), 30));
    test('полчаса', () => expect(parseIntervalMinutes('каждые полчаса'), 30));
    test('no minutes -> null', () => expect(parseIntervalMinutes('каждые 2 часа'), isNull));
  });
  group('parseTimeWindow', () {
    test('с 8 до 22', () => expect(parseTimeWindow('с 8 до 22'), (8, 22)));
    test('вечера shifts end', () => expect(parseTimeWindow('с 8 утра до 10 вечера'), (8, 22)));
    test('evening-only shifts start too', () => expect(parseTimeWindow('с 6 до 9 вечера'), (18, 21)));
    test('unparseable -> null', () => expect(parseTimeWindow('когда захочу'), isNull));
  });
}
