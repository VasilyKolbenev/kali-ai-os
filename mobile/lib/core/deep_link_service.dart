import 'dart:async';

import 'package:app_links/app_links.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../presentation/main_screen.dart';
import '../presentation/my_agents_screen.dart';
import '../standalone/agent_store.dart';
import '../standalone/bundle_importer.dart';
import '../standalone/imported_agent.dart';
import '../standalone/scheduling/notification_gateway.dart';
import '../standalone/scheduling/reminder_scheduler.dart';
import 'config.dart';
import 'http_client.dart';
import 'l10n.dart';
import 'standalone_mode.dart';
import 'token_store.dart';
import 'websocket_client.dart';

/// Global messenger key so deep-link results can surface a SnackBar from above
/// any Scaffold (the handler sits at the app root).
final scaffoldMessengerKey = GlobalKey<ScaffoldMessengerState>();

/// Global navigator key so the pairing deep-link can route to the main screen
/// from the app root (the connection screen does this via its own context).
final navigatorKey = GlobalKey<NavigatorState>();

/// Validated `ip` + `token` extracted from a `kali://pair` deep link.
class PairInfo {
  const PairInfo({required this.ip, required this.token});

  final String ip;
  final String token;
}

/// Parses a `kali://pair?ip=<host[:port]>&token=<token>` link into a [PairInfo],
/// or returns `null` for any non-pair / malformed link.
///
/// Validates that both values are present and non-empty and that the host looks
/// like a `host[:port]` (no spaces, parseable as a URI authority). Pure so the
/// parsing can be unit-tested without a Navigator or platform channels.
PairInfo? parsePairLink(Uri uri) {
  if (uri.scheme != 'kali' || uri.host != 'pair') return null;

  final ip = uri.queryParameters['ip']?.trim() ?? '';
  final token = uri.queryParameters['token']?.trim() ?? '';
  if (ip.isEmpty || token.isEmpty) return null;
  if (!_isPrivateHost(ip)) return null;

  return PairInfo(ip: ip, token: token);
}

/// Whether `value` (a `host[:port]`) is a private/loopback/CGNAT IPv4 literal.
///
/// Pairing is LAN-only by design: the token is the LAN-security boundary, so a
/// public host or a DNS name means an attacker is trying to exfiltrate the
/// token to a server they control. Only literal IPv4 in 10/8, 172.16/12,
/// 192.168/16, 127/8 or 100.64/10 is accepted; everything else (public IPs,
/// DNS names like `evil.com`/`localhost`, malformed input) is rejected.
bool _isPrivateHost(String value) {
  if (value.contains(RegExp(r'\s'))) return false;
  final probe = Uri.tryParse('http://$value');
  final host = probe?.host ?? '';
  if (host.isEmpty) return false;

  final octets = host.split('.');
  if (octets.length != 4) return false; // non-literal DNS name or IPv6
  final parts = <int>[];
  for (final o in octets) {
    // Strict ASCII-decimal, no leading zero: reject hex (0x7f) and octal-looking
    // (010) octets — int.tryParse would accept them as 127/10, but a libc-style
    // OS resolver reads 010 as octal 8 (public), diverging from this guard and
    // letting the token leak. Only canonical decimal octets pass.
    if (!RegExp(r'^(0|[1-9]\d{0,2})$').hasMatch(o)) return false;
    final n = int.parse(o);
    if (n > 255) return false;
    parts.add(n);
  }

  final a = parts[0];
  final b = parts[1];
  if (a == 10) return true; // 10.0.0.0/8
  if (a == 127) return true; // 127.0.0.0/8 (loopback)
  if (a == 192 && b == 168) return true; // 192.168.0.0/16
  if (a == 172 && b >= 16 && b <= 31) return true; // 172.16.0.0/12
  if (a == 100 && b >= 64 && b <= 127) return true; // 100.64.0.0/10 (CGNAT)
  return false;
}

/// Persists the paired token and updates the live in-memory holder, so a
/// freshly-scanned token takes effect with no app restart. Pure side effects
/// (no navigation) so it can be unit-tested.
Future<void> applyPairing(
  PairInfo info, {
  required TokenStore store,
  required TokenHolder holder,
}) async {
  await store.saveToken(info.token);
  holder.set(info.token);
}

/// Decides whether a `kali://import` should install on-device (standalone)
/// rather than via the paired desktop server.
///
/// On-device when the user explicitly chose standalone mode, OR when no desktop
/// is paired (no server IP). Pure so the branch is unit-testable.
bool shouldImportOnDevice({required bool standaloneMode, required String? serverIp}) =>
    standaloneMode || serverIp == null;

/// Persists a freshly-decoded [agent], carrying forward local reminder state.
///
/// Re-importing a same-name bundle must not silently reset the user's
/// `enabled` toggle / `snoozeUntil`: those are local to this device and the
/// sharer can't know them. So when an agent with the same name already exists,
/// we replace its shared content (`skillMd`/`description`/`config`/`template`)
/// while preserving the existing `enabled` + `snoozeUntil`. Returns the agent
/// actually persisted. Side-effect-only (no UI) so it stays unit-testable.
Future<ImportedAgent> saveImported(ImportedAgent agent,
    {required AgentStore store}) async {
  final existing = await store.get(agent.name);
  final toSave = existing == null
      ? agent
      : agent.copyWith(
          enabled: existing.enabled,
          snoozeUntil: existing.snoozeUntil,
        );
  await store.save(toSave);
  return toSave;
}

/// Imports a `kali://import` bundle on-device and persists it.
///
/// Decodes [payload] via [importBundle] then persists via [saveImported]
/// (which carries forward an existing agent's reminder state), returning the
/// stored agent. [importer] is injectable so tests stub the decode; in
/// production it defaults to [importBundle]. Lets a [BundleImportError]
/// propagate (the caller surfaces an honest snackbar).
Future<ImportedAgent> importOnDevice(
  String payload, {
  required AgentStore store,
  Future<ImportedAgent> Function(String)? importer,
}) async {
  final decode = importer ?? importBundle;
  final agent = await decode(payload);
  return saveImported(agent, store: store);
}

/// After a standalone import, registers the reminder's notifications.
///
/// Only reminder agents are scheduled: for them we request OS permission once
/// (via [gateway]) and trigger a full [ReminderScheduler.syncAll]. Conversational
/// agents are a no-op. Pure seam (no UI / navigation) so the import-side wiring
/// is unit-testable with a fake gateway and a fixed [now] clock.
Future<void> scheduleImportedReminder(
  ImportedAgent agent, {
  required ReminderScheduler scheduler,
  required NotificationGateway gateway,
  required DateTime now,
}) async {
  if (agent.template != 'reminder') return;
  await gateway.requestPermission();
  await scheduler.syncAll(now);
}

/// Listens for `kali://import?n=<name>&d=<base64url bundle>` deep links — the
/// import side of the UGC share loop.
///
/// The link is self-contained: the agent bundle travels inside it, so importing
/// needs only a connected backend (`/skills/install-bundle`), no catalog or
/// cloud. Wrap the app with [DeepLinkHandler]; it handles both cold-start links
/// (app launched by the link) and warm links (received while running).
class DeepLinkHandler extends ConsumerStatefulWidget {
  const DeepLinkHandler({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<DeepLinkHandler> createState() => _DeepLinkHandlerState();
}

class _DeepLinkHandlerState extends ConsumerState<DeepLinkHandler> {
  final AppLinks _appLinks = AppLinks();
  StreamSubscription<Uri>? _sub;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    try {
      final initial = await _appLinks.getInitialLink();
      if (initial != null) _handle(initial);
    } catch (_) {
      // No initial link, or a platform without deep-link support — ignore.
    }
    _sub = _appLinks.uriLinkStream.listen(_handle, onError: (_) {});
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  Future<void> _handle(Uri uri) async {
    final pair = parsePairLink(uri);
    if (pair != null) {
      await _handlePair(pair);
      return;
    }
    await _handleImport(uri);
  }

  /// Persists + holds the paired token, sets the server IP, then connects and
  /// routes into the main screen — the same destination the connection screen
  /// reaches after a successful connect.
  Future<void> _handlePair(PairInfo info) async {
    final holder = ref.read(tokenHolderProvider);
    await applyPairing(info, store: TokenStore(), holder: holder);

    ref.read(serverIpProvider.notifier).state = info.ip;

    final t = L10n.of(ref);
    final messenger = scaffoldMessengerKey.currentState;
    final connected = await ref.read(wsClientProvider).connect(info.ip);
    if (!connected) {
      messenger?.showSnackBar(SnackBar(content: Text(t.pairFailed)));
      return;
    }

    navigatorKey.currentState?.pushReplacement(
      MaterialPageRoute(builder: (_) => const MainScreen()),
    );
  }

  Future<void> _handleImport(Uri uri) async {
    if (uri.scheme != 'kali' || uri.host != 'import') return;
    final data = uri.queryParameters['d'];
    if (data == null || data.isEmpty) return;
    final name = uri.queryParameters['n'];

    final t = L10n.of(ref);
    final messenger = scaffoldMessengerKey.currentState;

    final ip = ref.read(serverIpProvider);
    final standalone = ref.read(standaloneModeProvider);

    if (ip == null ||
        shouldImportOnDevice(standaloneMode: standalone, serverIp: ip)) {
      await importStandaloneWithConsent(
        data: data,
        ref: ref,
        t: t,
        messenger: messenger,
        confirmContext: navigatorKey.currentContext,
      );
      return;
    }

    messenger?.showSnackBar(SnackBar(content: Text(t.importInstalling)));
    try {
      final resp = await ref.read(dioProvider).post(
        ServerConfig.api(ip, '/skills/install-bundle'),
        data: {
          'data': data,
          if (name != null && name.isNotEmpty) 'name': name,
          'overwrite': true,
        },
      );
      final body = resp.data as Map<String, dynamic>?;
      final ok = resp.statusCode == 200 && body?['status'] == 'ok';
      messenger?.hideCurrentSnackBar();
      if (ok) {
        final installed = (body?['skill_name'] ?? name ?? '').toString();
        messenger?.showSnackBar(SnackBar(content: Text(t.importOk(installed))));
      } else {
        messenger?.showSnackBar(SnackBar(content: Text(t.importFailed)));
      }
    } catch (_) {
      messenger?.hideCurrentSnackBar();
      messenger?.showSnackBar(SnackBar(content: Text(t.importFailed)));
    }
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// Decodes a `kali://import` bundle, asks the user to confirm, and only then
/// installs it on-device.
///
/// Consent-gated: `kali://import` brings an *untrusted* agent from a stranger's
/// share link, so we never silently persist it, flip to standalone, or request
/// notification permission. We decode first ([decoder], default [importBundle])
/// — a pure, side-effect-free step — to show the parsed name in a confirm sheet
/// ([confirm], default [showImportConsent]); the persist + permission + schedule
/// side effects run only after an explicit Confirm. A decode failure or a
/// cancel both leave the store and OS untouched. Injectable seams keep it
/// widget-testable without app_links or native channels.
Future<void> importStandaloneWithConsent({
  required String data,
  required WidgetRef ref,
  required L10n t,
  required ScaffoldMessengerState? messenger,
  required BuildContext? confirmContext,
  Future<ImportedAgent> Function(String)? decoder,
  Future<bool> Function(BuildContext, ImportedAgent, L10n)? confirm,
}) async {
  final decode = decoder ?? importBundle;
  final ask = confirm ?? showImportConsent;

  // Decode first (pure) so the confirm sheet can show the real name; a bad
  // bundle fails honestly here, before any side effect.
  final ImportedAgent decoded;
  try {
    decoded = await decode(data);
  } catch (_) {
    messenger?.showSnackBar(SnackBar(content: Text(t.importFailed)));
    return;
  }

  final ctx = confirmContext;
  // No live UI to confirm against (no Navigator yet, or it was torn down across
  // the decode await) — abort without any side effect.
  if (ctx == null || !ctx.mounted) return;
  final ok = await ask(ctx, decoded, t);
  if (!ok) return; // user declined: nothing persisted, no permission prompt

  // Confirmed: now flip to standalone, persist, request permission + schedule.
  ref.read(standaloneModeProvider.notifier).state = true;
  messenger?.showSnackBar(SnackBar(content: Text(t.importInstalling)));
  try {
    // Carry forward any existing enabled/snooze state on a same-name re-import.
    await saveImported(decoded, store: ref.read(agentStoreProvider));
    // Reminder agents start firing immediately; conversational ones don't.
    await scheduleImportedReminder(
      decoded,
      scheduler: ref.read(reminderSchedulerProvider),
      gateway: ref.read(notificationGatewayProvider),
      now: DateTime.now(),
    );
    messenger?.hideCurrentSnackBar();
    messenger?.showSnackBar(
      SnackBar(content: Text(t.importedStandalone(decoded.name))),
    );
    navigatorKey.currentState?.pushReplacement(
      MaterialPageRoute(builder: (_) => const MainScreen()),
    );
  } catch (_) {
    messenger?.hideCurrentSnackBar();
    messenger?.showSnackBar(SnackBar(content: Text(t.importFailed)));
  }
}

/// Shows the import-consent dialog for [agent] and resolves to the user's
/// choice (true = install). One extra tap, to keep the UGC flow frictionless
/// while never installing a stranger's agent silently.
Future<bool> showImportConsent(
  BuildContext context,
  ImportedAgent agent,
  L10n t,
) async {
  final result = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(t.importConfirmTitle),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(t.importConfirmBody(agent.name)),
          if (agent.description.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(agent.description),
          ],
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(ctx).pop(false),
          child: Text(t.importConfirmCancel),
        ),
        FilledButton(
          onPressed: () => Navigator.of(ctx).pop(true),
          child: Text(t.importConfirmInstall),
        ),
      ],
    ),
  );
  return result ?? false;
}
