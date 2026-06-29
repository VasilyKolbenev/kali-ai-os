// Unit tests for the share-to-reels content-type branch (UGC reel hook).
//
// The reel fetch in `_prepare()` decides reel-vs-fallback purely from the
// response's content-type (NOT the status code alone): a `video/mp4` body with
// bytes becomes the shared MP4; anything else (JSON error, empty, non-video)
// falls back to the PNG card / text+link. That decision is isolated in the
// pure static helper `ShareToReelsScreen.isReelResponse` so it is testable
// without the native share sheet / path_provider channels.

import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:kali_mobile/presentation/share_to_reels_screen.dart';

Response<dynamic> _resp({
  required String? contentType,
  required dynamic data,
  int statusCode = 200,
}) {
  final headers = Headers();
  if (contentType != null) {
    headers.set(Headers.contentTypeHeader, contentType);
  }
  return Response<dynamic>(
    requestOptions: RequestOptions(path: '/skills/Foo/reel'),
    statusCode: statusCode,
    headers: headers,
    data: data,
  );
}

void main() {
  test('video/mp4 with non-empty bytes is treated as a reel', () {
    final resp = _resp(
      contentType: 'video/mp4',
      data: Uint8List.fromList(<int>[0, 0, 0, 24, 102, 116, 121, 112]),
    );
    expect(ShareToReelsScreen.isReelResponse(resp), isTrue);
  });

  test('content-type with charset suffix still counts as a reel', () {
    final resp = _resp(
      contentType: 'video/mp4; charset=binary',
      data: Uint8List.fromList(<int>[1, 2, 3, 4]),
    );
    expect(ShareToReelsScreen.isReelResponse(resp), isTrue);
  });

  test('application/json error body falls back (not a reel)', () {
    final resp = _resp(
      contentType: 'application/json',
      data: '{"status":"error","name":"Foo","message":"render failed"}',
    );
    expect(ShareToReelsScreen.isReelResponse(resp), isFalse);
  });

  test('video/mp4 with empty bytes falls back (not a reel)', () {
    final resp = _resp(
      contentType: 'video/mp4',
      data: Uint8List(0),
    );
    expect(ShareToReelsScreen.isReelResponse(resp), isFalse);
  });

  test('missing content-type falls back (not a reel)', () {
    final resp = _resp(
      contentType: null,
      data: Uint8List.fromList(<int>[1, 2, 3]),
    );
    expect(ShareToReelsScreen.isReelResponse(resp), isFalse);
  });

  test('non-200 status falls back even with video/mp4', () {
    final resp = _resp(
      contentType: 'video/mp4',
      data: Uint8List.fromList(<int>[1, 2, 3]),
      statusCode: 500,
    );
    expect(ShareToReelsScreen.isReelResponse(resp), isFalse);
  });
}
