import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Current app locale. Defaults to Russian.
final localeProvider = StateProvider<String>((ref) => 'ru');

/// Available languages for the UI.
const supportedLocales = {
  'ru': '\u0420\u0443\u0441\u0441\u043a\u0438\u0439',        // Русский
  'en': 'English',
  'es': 'Espa\u00f1ol',
  'zh': '\u4e2d\u6587',            // 中文
  'de': 'Deutsch',
};

/// Localization helper. Usage:
/// ```dart
/// final t = L10n.of(ref);
/// Text(t.greeting);
/// ```
class L10n {
  final String _locale;
  L10n(this._locale);

  /// Convenience constructor from a WidgetRef.
  factory L10n.of(dynamic ref) {
    final locale = ref.read(localeProvider);
    return L10n(locale);
  }

  String get locale => _locale;

  // ── Navigation ──
  String get navHome => _t({'ru': '\u0413\u043b\u0430\u0432\u043d\u0430\u044f', 'en': 'Home', 'es': 'Inicio', 'zh': '\u9996\u9875', 'de': 'Start'});
  String get navVoice => _t({'ru': '\u0413\u043e\u043b\u043e\u0441', 'en': 'Voice', 'es': 'Voz', 'zh': '\u8bed\u97f3', 'de': 'Stimme'});
  String get navChat => _t({'ru': '\u0427\u0430\u0442', 'en': 'Chat', 'es': 'Chat', 'zh': '\u804a\u5929', 'de': 'Chat'});
  String get navAgents => _t({'ru': '\u0410\u0433\u0435\u043d\u0442\u044b', 'en': 'Agents', 'es': 'Agentes', 'zh': '\u667a\u80fd\u4f53', 'de': 'Agenten'});
  String get navSettings => _t({'ru': '\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438', 'en': 'Settings', 'es': 'Ajustes', 'zh': '\u8bbe\u7f6e', 'de': 'Einstellungen'});

  // ── Connection Screen ──
  String get connectTitle => _t({'ru': '\u041f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u0435 \u043a KALI', 'en': 'Connect to KALI', 'es': 'Conectar a KALI', 'zh': '\u8fde\u63a5 KALI', 'de': 'Mit KALI verbinden'});
  String get connectSubtitle => _t({'ru': '\u0412\u0432\u0435\u0434\u0438\u0442\u0435 IP-\u0430\u0434\u0440\u0435\u0441 \u043a\u043e\u043c\u043f\u044c\u044e\u0442\u0435\u0440\u0430,\n\u043d\u0430 \u043a\u043e\u0442\u043e\u0440\u043e\u043c \u0437\u0430\u043f\u0443\u0449\u0435\u043d KALI Desktop', 'en': 'Enter the IP address of the\ncomputer running KALI Desktop', 'es': 'Ingresa la IP del ordenador\ncon KALI Desktop', 'zh': '\u8f93\u5165\u8fd0\u884cKALI Desktop\u7684\u7535\u8111IP', 'de': 'Gib die IP des Computers\nmit KALI Desktop ein'});
  String get connectHint => _t({'ru': 'IP-\u0430\u0434\u0440\u0435\u0441 \u043a\u043e\u043c\u043f\u044c\u044e\u0442\u0435\u0440\u0430', 'en': 'Computer IP address', 'es': 'Direcci\u00f3n IP', 'zh': '\u7535\u8111IP\u5730\u5740', 'de': 'Computer IP-Adresse'});
  String get connectButton => _t({'ru': '\u041f\u043e\u0434\u043a\u043b\u044e\u0447\u0438\u0442\u044c\u0441\u044f', 'en': 'Connect', 'es': 'Conectar', 'zh': '\u8fde\u63a5', 'de': 'Verbinden'});
  String get connectTip => _t({'ru': '\u041e\u0442\u043a\u0440\u043e\u0439\u0442\u0435 KALI Desktop \u043d\u0430 \u043a\u043e\u043c\u043f\u044c\u044e\u0442\u0435\u0440\u0435 \u0438 \u043f\u043e\u0441\u043c\u043e\u0442\u0440\u0438\u0442\u0435\nIP \u0432 \u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0430\u0445 \u2192 \u041f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u0435', 'en': 'Open KALI Desktop on your computer\nand find the IP in Settings \u2192 Connection', 'es': 'Abre KALI Desktop y busca\nla IP en Ajustes \u2192 Conexi\u00f3n', 'zh': '\u5728\u7535\u8111\u4e0a\u6253\u5f00KALI Desktop\n\u5728\u8bbe\u7f6e\u2192\u8fde\u63a5\u4e2d\u67e5\u770bIP', 'de': '\u00d6ffne KALI Desktop am PC und\nfinde die IP unter Einstellungen \u2192 Verbindung'});
  String connectFailed(String ip) => _t({'ru': '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0438\u0442\u044c\u0441\u044f \u043a $ip', 'en': 'Failed to connect to $ip', 'es': 'Error al conectar a $ip', 'zh': '\u65e0\u6cd5\u8fde\u63a5\u5230 $ip', 'de': 'Verbindung zu $ip fehlgeschlagen'});

  // ── Dashboard ──
  String get greetMorning => _t({'ru': '\u0414\u043e\u0431\u0440\u043e\u0435 \u0443\u0442\u0440\u043e,', 'en': 'Good morning,', 'es': 'Buenos d\u00edas,', 'zh': '\u65e9\u4e0a\u597d,', 'de': 'Guten Morgen,'});
  String get greetAfternoon => _t({'ru': '\u0414\u043e\u0431\u0440\u044b\u0439 \u0434\u0435\u043d\u044c,', 'en': 'Good afternoon,', 'es': 'Buenas tardes,', 'zh': '\u4e0b\u5348\u597d,', 'de': 'Guten Tag,'});
  String get greetEvening => _t({'ru': '\u0414\u043e\u0431\u0440\u044b\u0439 \u0432\u0435\u0447\u0435\u0440,', 'en': 'Good evening,', 'es': 'Buenas noches,', 'zh': '\u665a\u4e0a\u597d,', 'de': 'Guten Abend,'});
  String get greetNight => _t({'ru': '\u0414\u043e\u0431\u0440\u043e\u0439 \u043d\u043e\u0447\u0438,', 'en': 'Good night,', 'es': 'Buenas noches,', 'zh': '\u665a\u5b89,', 'de': 'Gute Nacht,'});
  String get userName => _t({'ru': '\u0421\u044d\u0440', 'en': 'Sir', 'es': 'Se\u00f1or', 'zh': '\u5148\u751f', 'de': 'Sir'});
  String get insightTitle => 'Jarvis Insight';
  String get insightText => _t({'ru': '\u0423 \u0432\u0430\u0441 \u0432\u0441\u0442\u0440\u0435\u0447\u0430 \u0447\u0435\u0440\u0435\u0437 30 \u043c\u0438\u043d\u0443\u0442, \u043f\u0440\u043e\u0431\u043a\u0438 \u0441\u0440\u0435\u0434\u043d\u0438\u0435 \u2014 \u0440\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0443\u044e \u0432\u044b\u0435\u0445\u0430\u0442\u044c \u0432 14:30.', 'en': 'You have a meeting in 30 minutes, traffic is moderate \u2014 I recommend leaving at 14:30.', 'es': 'Tiene una reuni\u00f3n en 30 min, tr\u00e1fico moderado \u2014 salga a las 14:30.', 'zh': '30\u5206\u949f\u540e\u6709\u4f1a\u8bae\uff0c\u4ea4\u901a\u4e00\u822c\u2014\u5efa\u8bae14:30\u51fa\u53d1\u3002', 'de': 'In 30 Min ein Meeting, Verkehr m\u00e4\u00dfig \u2014 Empfehlung: 14:30 losfahren.'});
  String get agentReady => _t({'ru': '\u0412\u0430\u0448 \u043d\u043e\u0432\u044b\u0439 \u0430\u0433\u0435\u043d\u0442 \u0433\u043e\u0442\u043e\u0432', 'en': 'Your new agent is ready', 'es': 'Tu nuevo agente est\u00e1 listo', 'zh': '\u60a8\u7684\u65b0\u667a\u80fd\u4f53\u5df2\u5c31\u7eea', 'de': 'Ihr neuer Agent ist bereit'});
  String get shareInReels => _t({'ru': '\u041f\u043e\u0434\u0435\u043b\u0438\u0442\u0435\u0441\u044c \u0438\u043c \u0432 Reels', 'en': 'Share it in Reels', 'es': 'Comp\u00e1rtelo en Reels', 'zh': '\u5206\u4eab\u5230Reels', 'de': 'In Reels teilen'});
  String get lifeGlance => _t({'ru': '\u041c\u043e\u044f \u0436\u0438\u0437\u043d\u044c \u0432 \u0446\u0438\u0444\u0440\u0430\u0445', 'en': 'My Life at a Glance', 'es': 'Mi Vida de un Vistazo', 'zh': '\u6211\u7684\u751f\u6d3b\u6982\u89c8', 'de': 'Mein Leben auf einen Blick'});
  String get weather => _t({'ru': '\u041f\u043e\u0433\u043e\u0434\u0430', 'en': 'Weather', 'es': 'Clima', 'zh': '\u5929\u6c14', 'de': 'Wetter'});
  String get sunny => _t({'ru': '\u0421\u043e\u043b\u043d\u0435\u0447\u043d\u043e', 'en': 'Sunny', 'es': 'Soleado', 'zh': '\u6674\u6717', 'de': 'Sonnig'});
  String get budget => _t({'ru': '\u0411\u044e\u0434\u0436\u0435\u0442', 'en': 'Budget', 'es': 'Presupuesto', 'zh': '\u9884\u7b97', 'de': 'Budget'});
  String get budgetLeft => _t({'ru': '\u041e\u0441\u0442\u0430\u0442\u043e\u043a \u043d\u0430 \u0434\u0435\u043d\u044c', 'en': 'Left for today', 'es': 'Restante hoy', 'zh': '\u4eca\u65e5\u4f59\u989d', 'de': 'Rest f\u00fcr heute'});
  String get tasks => _t({'ru': '\u0417\u0430\u0434\u0430\u0447\u0438', 'en': 'Tasks', 'es': 'Tareas', 'zh': '\u4efb\u52a1', 'de': 'Aufgaben'});
  String active(int n) => _t({'ru': '$n \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0435', 'en': '$n active', 'es': '$n activas', 'zh': '$n\u4e2a\u8fdb\u884c\u4e2d', 'de': '$n aktiv'});
  String get defaultTasksSub => _t({'ru': '\u0421\u0442\u0435\u043d\u0434\u0430\u043f \u0432 10:00, \u041e\u0431\u0435\u0434 \u0441 \u041c\u0430\u043a\u0441\u043e\u043c', 'en': 'Standup at 10:00, Lunch with Max', 'es': 'Standup a las 10:00, Almuerzo con Max', 'zh': '10\u70b9\u7ad9\u4f1a, \u4e0eMax\u5348\u9910', 'de': 'Standup um 10:00, Mittagessen mit Max'});
  String get budgetTracker => _t({'ru': '\u0411\u044e\u0434\u0436\u0435\u0442\u043d\u044b\u0439 \u0442\u0440\u0435\u043a\u0435\u0440', 'en': 'Budget Tracker', 'es': 'Rastreador de gastos', 'zh': '\u9884\u7b97\u8ffd\u8e2a\u5668', 'de': 'Budget-Tracker'});
  String get budgetTrackerDesc => _t({'ru': '\u0417\u0430\u043a\u0438\u0434\u044b\u0432\u0430\u0435\u0448\u044c \u0444\u043e\u0442\u043a\u0443 \u0447\u0435\u043a\u0430, \u0430 \u043e\u043d \u0441\u0430\u043c \u0432\u043d\u043e\u0441\u0438\u0442 \u0442\u0440\u0430\u0442\u044b \u0432 Notion!', 'en': 'Snap a receipt photo and expenses go to Notion!', 'es': '\u00a1Toma una foto del recibo y los gastos van a Notion!', 'zh': '\u62cd\u7167\u6536\u636e\uff0c\u81ea\u52a8\u8bb0\u5f55\u5230Notion\uff01', 'de': 'Kassenbon fotografieren \u2014 Ausgaben landen in Notion!'});

  // ── Voice Screen ──
  String get voiceIdle => _t({'ru': '\u0413\u041e\u0422\u041e\u0412', 'en': 'READY', 'es': 'LISTO', 'zh': '\u5c31\u7eea', 'de': 'BEREIT'});
  String get voiceListening => _t({'ru': '\u0421\u041b\u0423\u0428\u0410\u042e', 'en': 'LISTENING', 'es': 'ESCUCHANDO', 'zh': '\u542c\u53d6\u4e2d', 'de': 'H\u00d6RE ZU'});
  String get voiceThinking => _t({'ru': '\u0414\u0423\u041c\u0410\u042e', 'en': 'THINKING', 'es': 'PENSANDO', 'zh': '\u601d\u8003\u4e2d', 'de': 'DENKE NACH'});
  String get voiceSpeaking => _t({'ru': '\u0413\u041e\u0412\u041e\u0420\u042e', 'en': 'SPEAKING', 'es': 'HABLANDO', 'zh': '\u56de\u7b54\u4e2d', 'de': 'SPRECHE'});
  String get voiceTapHint => _t({'ru': '\u041d\u0430\u0436\u043c\u0438\u0442\u0435 \u043d\u0430 \u043a\u0440\u0443\u0433, \u0447\u0442\u043e\u0431\u044b \u0433\u043e\u0432\u043e\u0440\u0438\u0442\u044c', 'en': 'Tap the orb to speak', 'es': 'Toca el orbe para hablar', 'zh': '\u70b9\u51fb\u5f00\u59cb\u8bf4\u8bdd', 'de': 'Tippe zum Sprechen'});
  String get voiceListeningHint => _t({'ru': '\u0421\u043b\u0443\u0448\u0430\u044e...', 'en': 'Listening...', 'es': 'Escuchando...', 'zh': '\u542c\u53d6\u4e2d...', 'de': 'H\u00f6re zu...'});
  String get voiceTryHint => _t({'ru': '\u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435: \u00abDjarvis, \u043a\u0430\u043a\u0430\u044f \u043f\u043e\u0433\u043e\u0434\u0430?\u00bb', 'en': 'Try: "Jarvis, what\u0027s the weather?"', 'es': 'Prueba: "Jarvis, \u00bfqu\u00e9 tiempo hace?"', 'zh': '\u8bd5\u8bd5: \u201cJarvis, \u5929\u6c14\u600e\u4e48\u6837?\u201d', 'de': 'Versuche: \u201eJarvis, wie ist das Wetter?\u201c'});

  // ── Chat Screen ──
  String get chatTitle => _t({'ru': '\u0427\u0430\u0442 \u0441 Jarvis', 'en': 'Chat with Jarvis', 'es': 'Chat con Jarvis', 'zh': '\u4e0eJarvis\u804a\u5929', 'de': 'Chat mit Jarvis'});
  String get chatEmpty => _t({'ru': '\u041d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435...', 'en': 'Start a conversation...', 'es': 'Inicia una conversaci\u00f3n...', 'zh': '\u5f00\u59cb\u5bf9\u8bdd...', 'de': 'Schreibe eine Nachricht...'});
  String get chatInputHint => _t({'ru': '\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435...', 'en': 'Message...', 'es': 'Mensaje...', 'zh': '\u8f93\u5165\u6d88\u606f...', 'de': 'Nachricht...'});
  String get chatTyping => _t({'ru': 'Jarvis \u043f\u0438\u0448\u0435\u0442...', 'en': 'Jarvis is typing...', 'es': 'Jarvis est\u00e1 escribiendo...', 'zh': 'Jarvis\u8f93\u5165\u4e2d...', 'de': 'Jarvis schreibt...'});
  String get notConnected => _t({'ru': '\u041d\u0435\u0442 \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f \u043a \u0441\u0435\u0440\u0432\u0435\u0440\u0443', 'en': 'Not connected to server', 'es': 'Sin conexi\u00f3n al servidor', 'zh': '\u672a\u8fde\u63a5\u670d\u52a1\u5668', 'de': 'Nicht mit Server verbunden'});

  // ── Agent Store ──
  String get agentStoreTitle => _t({'ru': '\u041c\u0430\u0433\u0430\u0437\u0438\u043d \u0430\u0433\u0435\u043d\u0442\u043e\u0432', 'en': 'Agent Store', 'es': 'Tienda de Agentes', 'zh': '\u667a\u80fd\u4f53\u5546\u5e97', 'de': 'Agenten-Store'});
  String get installed => _t({'ru': '\u0423\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u043d\u044b\u0435', 'en': 'Installed', 'es': 'Instalados', 'zh': '\u5df2\u5b89\u88c5', 'de': 'Installiert'});
  String get discover => _t({'ru': '\u041a\u0430\u0442\u0430\u043b\u043e\u0433', 'en': 'Discover', 'es': 'Explorar', 'zh': '\u53d1\u73b0', 'de': 'Entdecken'});
  String get noAgents => _t({'ru': '\u041d\u0435\u0442 \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u043d\u044b\u0445 \u0430\u0433\u0435\u043d\u0442\u043e\u0432', 'en': 'No agents installed', 'es': 'No hay agentes instalados', 'zh': '\u6ca1\u6709\u5df2\u5b89\u88c5\u7684\u667a\u80fd\u4f53', 'de': 'Keine Agenten installiert'});
  String get noCatalog => _t({'ru': '\u041a\u0430\u0442\u0430\u043b\u043e\u0433 \u043f\u0443\u0441\u0442', 'en': 'No skills found in catalog', 'es': 'Cat\u00e1logo vac\u00edo', 'zh': '\u76ee\u5f55\u4e3a\u7a7a', 'de': 'Katalog leer'});
  String get install => _t({'ru': '\u0423\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u044c', 'en': 'Install', 'es': 'Instalar', 'zh': '\u5b89\u88c5', 'de': 'Installieren'});
  String installing(String name) => _t({'ru': '\u0423\u0441\u0442\u0430\u043d\u0430\u0432\u043b\u0438\u0432\u0430\u0435\u043c $name...', 'en': 'Installing $name...', 'es': 'Instalando $name...', 'zh': '\u6b63\u5728\u5b89\u88c5 $name...', 'de': 'Installiere $name...'});
  String installOk(String name) => _t({'ru': '$name \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d!', 'en': '$name installed!', 'es': '\u00a1$name instalado!', 'zh': '$name \u5df2\u5b89\u88c5!', 'de': '$name installiert!'});
  String get installFailed => _t({'ru': '\u041e\u0448\u0438\u0431\u043a\u0430 \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0438', 'en': 'Installation failed', 'es': 'Error de instalaci\u00f3n', 'zh': '\u5b89\u88c5\u5931\u8d25', 'de': 'Installation fehlgeschlagen'});
  String get toggleFailed => _t({'ru': '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0438\u0442\u044c \u0430\u0433\u0435\u043d\u0442\u0430', 'en': 'Failed to toggle agent', 'es': 'Error al cambiar agente', 'zh': '\u5207\u6362\u5931\u8d25', 'de': 'Agent-Umschalten fehlgeschlagen'});

  // ── Settings ──
  String get settingsTitle => _t({'ru': '\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438', 'en': 'Settings', 'es': 'Ajustes', 'zh': '\u8bbe\u7f6e', 'de': 'Einstellungen'});
  String get settingsAI => _t({'ru': '\u0418\u0441\u043a\u0443\u0441\u0441\u0442\u0432\u0435\u043d\u043d\u044b\u0439 \u0438\u043d\u0442\u0435\u043b\u043b\u0435\u043a\u0442', 'en': 'Artificial Intelligence', 'es': 'Inteligencia Artificial', 'zh': '\u4eba\u5de5\u667a\u80fd', 'de': 'K\u00fcnstliche Intelligenz'});
  String get settingsAIProvider => _t({'ru': '\u041c\u043e\u0437\u0433 Jarvis (\u043f\u0440\u043e\u0432\u0430\u0439\u0434\u0435\u0440)', 'en': 'Jarvis Brain (provider)', 'es': 'Cerebro de Jarvis (proveedor)', 'zh': 'Jarvis\u5927\u8111 (\u63d0\u4f9b\u5546)', 'de': 'Jarvis-Gehirn (Anbieter)'});
  String get settingsVoice => _t({'ru': '\u0413\u043e\u043b\u043e\u0441 \u0438 \u0440\u0435\u0447\u044c', 'en': 'Voice & Speech', 'es': 'Voz y Habla', 'zh': '\u8bed\u97f3\u4e0e\u8bed\u8a00', 'de': 'Stimme & Sprache'});
  String get settingsSTT => _t({'ru': '\u0420\u0430\u0441\u043f\u043e\u0437\u043d\u0430\u0432\u0430\u043d\u0438\u0435 \u0440\u0435\u0447\u0438', 'en': 'Speech Recognition', 'es': 'Reconocimiento de voz', 'zh': '\u8bed\u97f3\u8bc6\u522b', 'de': 'Spracherkennung'});
  String get settingsTTS => _t({'ru': '\u0413\u043e\u043b\u043e\u0441 Jarvis', 'en': 'Jarvis Voice', 'es': 'Voz de Jarvis', 'zh': 'Jarvis\u58f0\u97f3', 'de': 'Jarvis-Stimme'});
  String get settingsLanguage => _t({'ru': '\u042f\u0437\u044b\u043a \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u044f', 'en': 'App Language', 'es': 'Idioma de la app', 'zh': '\u5e94\u7528\u8bed\u8a00', 'de': 'App-Sprache'});
  String get settingsGeneral => _t({'ru': '\u041e\u0431\u0449\u0438\u0435', 'en': 'General', 'es': 'General', 'zh': '\u901a\u7528', 'de': 'Allgemein'});
  String get disconnect => _t({'ru': '\u041e\u0442\u043a\u043b\u044e\u0447\u0438\u0442\u044c\u0441\u044f \u043e\u0442 \u043a\u043e\u043c\u043f\u044c\u044e\u0442\u0435\u0440\u0430', 'en': 'Disconnect from Desktop', 'es': 'Desconectar del escritorio', 'zh': '\u65ad\u5f00\u8fde\u63a5', 'de': 'Vom Desktop trennen'});
  String get settingSaved => _t({'ru': '\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0430 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0430', 'en': 'Setting saved', 'es': 'Ajuste guardado', 'zh': '\u8bbe\u7f6e\u5df2\u4fdd\u5b58', 'de': 'Einstellung gespeichert'});
  String saveFailed(String e) => _t({'ru': '\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0438\u044f: $e', 'en': 'Failed to save: $e', 'es': 'Error al guardar: $e', 'zh': '\u4fdd\u5b58\u5931\u8d25: $e', 'de': 'Speichern fehlgeschlagen: $e'});

  // ── Share to Reels ──
  String get reelsCaption => _t({'ru': '\u0421\u043c\u043e\u0442\u0440\u0438 \u043a\u0430\u043a\u043e\u0433\u043e \u0430\u0433\u0435\u043d\u0442\u0430 \u044f \u0442\u043e\u043b\u044c\u043a\u043e \u0447\u0442\u043e \u0441\u043e\u0437\u0434\u0430\u043b \u0433\u043e\u043b\u043e\u0441\u043e\u043c \u0437\u0430 10 \u0441\u0435\u043a\u0443\u043d\u0434! \ud83e\udd2f', 'en': 'Check out the agent I just created by voice in 10 seconds! \ud83e\udd2f', 'es': '\u00a1Mira el agente que acabo de crear por voz en 10 segundos! \ud83e\udd2f', 'zh': '\u770b\u770b\u621110\u79d2\u5185\u7528\u8bed\u97f3\u521b\u5efa\u7684\u667a\u80fd\u4f53! \ud83e\udd2f', 'de': 'Schau, welchen Agenten ich gerade per Sprache in 10 Sek. erstellt habe! \ud83e\udd2f'});
  String get reelsDownload => _t({'ru': '\u0421\u043a\u0430\u0447\u0430\u0439 \u043c\u043e\u0435\u0433\u043e \u0430\u0433\u0435\u043d\u0442\u0430', 'en': 'Download my agent', 'es': 'Descarga mi agente', 'zh': '\u4e0b\u8f7d\u6211\u7684\u667a\u80fd\u4f53', 'de': 'Lade meinen Agenten'});
  String get reelsPublish => _t({'ru': '\u041e\u043f\u0443\u0431\u043b\u0438\u043a\u043e\u0432\u0430\u0442\u044c \u0432 Reels / TikTok', 'en': 'Publish to Reels / TikTok', 'es': 'Publicar en Reels / TikTok', 'zh': '\u53d1\u5e03\u5230 Reels / TikTok', 'de': 'In Reels / TikTok ver\u00f6ffentlichen'});
  String get reelsExporting => _t({'ru': '\u042d\u043a\u0441\u043f\u043e\u0440\u0442 \u0432 TikTok / Instagram...', 'en': 'Exporting to TikTok / Instagram...', 'es': 'Exportando a TikTok / Instagram...', 'zh': '\u5bfc\u51fa\u5230 TikTok / Instagram...', 'de': 'Export nach TikTok / Instagram...'});

  // ── Generic ──
  String get share => _t({'ru': '\u041f\u043e\u0434\u0435\u043b\u0438\u0442\u044c\u0441\u044f', 'en': 'Share', 'es': 'Compartir', 'zh': '\u5206\u4eab', 'de': 'Teilen'});
  String error(String e) => _t({'ru': '\u041e\u0448\u0438\u0431\u043a\u0430: $e', 'en': 'Error: $e', 'es': 'Error: $e', 'zh': '\u9519\u8bef: $e', 'de': 'Fehler: $e'});

  // ── Internal ──
  String _t(Map<String, String> map) => map[_locale] ?? map['en'] ?? '';
}
