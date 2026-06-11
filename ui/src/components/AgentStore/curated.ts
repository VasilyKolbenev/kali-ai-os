/**
 * Curated storefront data — the human face of the store.
 *
 * Non-tech users see THESE cards (RU titles, benefit-first descriptions,
 * life categories), never raw GitHub catalog metadata. Entries either wrap
 * a built-in agent (kind: "agent" — works offline, «Включить») or reference
 * an installable SKILL.md from a catalog source (kind: "skill" — 1-click
 * install by source ref, no catalog browsing required).
 *
 * The dev-oriented source catalog stays available behind «Для продвинутых».
 */

export type CategoryId =
  | "all"
  | "reminders"
  | "health"
  | "home"
  | "money"
  | "news"
  | "chat"
  | "docs"
  | "community";

export interface Category {
  id: CategoryId;
  label: string;
  emoji: string;
}

export const CATEGORIES: Category[] = [
  { id: "all", label: "Все", emoji: "✨" },
  { id: "reminders", label: "Напоминания и списки", emoji: "📅" },
  { id: "health", label: "Здоровье", emoji: "💧" },
  { id: "home", label: "Дом", emoji: "🏠" },
  { id: "money", label: "Деньги", emoji: "💱" },
  { id: "news", label: "Новости и погода", emoji: "🌤" },
  { id: "chat", label: "Общение", emoji: "💬" },
  { id: "docs", label: "Документы", emoji: "📄" },
  { id: "community", label: "Сообщество", emoji: "🤝" },
];

export interface SetupGuide {
  /** What the user needs, in plain words: «Ключ Telegram-бота». */
  what: string;
  /** Plain RU steps to get it. */
  steps: string[];
  /** Optional external page that issues the key. */
  url?: string;
}

export interface CuratedEntry {
  id: string;
  title: string;
  /** One line: what the user GETS, not what the tech does. */
  benefit: string;
  emoji: string;
  category: Exclude<CategoryId, "all" | "community">;
  kind: "agent" | "skill";
  /** kind=agent: name in /agents (built-in, works offline). */
  agentName?: string;
  /** kind=skill: install reference into the skills catalog. */
  source?: { sourceId: string; name: string };
  setup?: SetupGuide;
  /** Search keywords (RU + EN synonyms). */
  keywords?: string[];
}

export const CURATED: CuratedEntry[] = [
  // — Напоминания и списки —
  {
    id: "calendar",
    title: "Календарь",
    benefit: "Запомнит события и напомнит о встречах",
    emoji: "📅",
    category: "reminders",
    kind: "agent",
    agentName: "calendar",
    keywords: ["календарь", "событие", "встреча", "calendar"],
  },
  {
    id: "tasks",
    title: "Задачи",
    benefit: "Список дел голосом: добавляй и отмечай сделанное",
    emoji: "✅",
    category: "reminders",
    kind: "agent",
    agentName: "tasks",
    keywords: ["задачи", "дела", "список", "todo"],
  },
  {
    id: "life-dashboard",
    title: "Сводка дня",
    benefit: "Утренний обзор: события, задачи и важное одним взглядом",
    emoji: "📊",
    category: "reminders",
    kind: "agent",
    agentName: "life-dashboard",
    keywords: ["сводка", "день", "брифинг", "dashboard"],
  },
  {
    id: "todoist",
    title: "Todoist",
    benefit: "Подружится с твоим Todoist: задачи появятся и там",
    emoji: "📝",
    category: "reminders",
    kind: "agent",
    agentName: "todoist",
    setup: {
      what: "Ключ Todoist (API-токен)",
      steps: [
        "Открой todoist.com и войди в свой аккаунт",
        "Настройки → Интеграции → вкладка «Для разработчиков»",
        "Скопируй API-токен и вставь его в Настройках KALI",
      ],
      url: "https://app.todoist.com/app/settings/integrations/developer",
    },
    keywords: ["todoist", "задачи"],
  },

  // — Здоровье —
  {
    id: "water",
    title: "Вода",
    benefit: "Напомнит пить воду и посчитает дневную норму",
    emoji: "💧",
    category: "health",
    kind: "agent",
    agentName: "water-tracker",
    keywords: ["вода", "пить", "напомни", "water"],
  },

  // — Дом —
  {
    id: "smart-home",
    title: "Умный дом",
    benefit: "Свет, розетки и сценарии — голосом",
    emoji: "🏠",
    category: "home",
    kind: "agent",
    agentName: "smart-home",
    setup: {
      what: "Подключение к твоему хабу умного дома",
      steps: [
        "Открой Настройки KALI → раздел «Умный дом»",
        "Укажи адрес хаба (Home Assistant / Tuya) и токен доступа",
        "Скажи: «Джарвис, включи свет» — проверим вместе",
      ],
    },
    keywords: ["дом", "свет", "розетка", "home"],
  },

  // — Деньги —
  {
    id: "currency",
    title: "Курсы валют и крипты",
    benefit: "Доллар, евро и биткоин — спроси в любой момент",
    emoji: "💱",
    category: "money",
    kind: "agent",
    agentName: "currency",
    keywords: ["курс", "доллар", "евро", "биткоин", "крипта", "currency"],
  },

  // — Новости и погода —
  {
    id: "weather",
    title: "Погода",
    benefit: "Погода сейчас и прогноз на 3 дня в любом городе",
    emoji: "🌤",
    category: "news",
    kind: "agent",
    agentName: "weather",
    keywords: ["погода", "прогноз", "дождь", "weather"],
  },
  {
    id: "news",
    title: "Новости",
    benefit: "Свежие заголовки по темам, которые тебе интересны",
    emoji: "📰",
    category: "news",
    kind: "agent",
    agentName: "news",
    keywords: ["новости", "заголовки", "news"],
  },
  {
    id: "web-surfer",
    title: "Интернет-помощник",
    benefit: "Найдёт и перескажет любую страницу из интернета",
    emoji: "🔍",
    category: "news",
    kind: "agent",
    agentName: "web-surfer",
    keywords: ["поиск", "интернет", "найди", "search"],
  },

  // — Общение —
  {
    id: "telegram",
    title: "Telegram",
    benefit: "Пришлёт сообщение или уведомление прямо в Telegram",
    emoji: "✈️",
    category: "chat",
    kind: "agent",
    agentName: "telegram",
    setup: {
      what: "Ключ Telegram-бота",
      steps: [
        "В Telegram найди @BotFather и напиши ему /newbot",
        "Придумай имя — BotFather пришлёт ключ (токен)",
        "Вставь ключ в Настройках KALI → «Telegram»",
      ],
      url: "https://t.me/BotFather",
    },
    keywords: ["телеграм", "сообщение", "telegram", "бот"],
  },
  {
    id: "email",
    title: "Почта",
    benefit: "Прочитает и отправит письма за тебя",
    emoji: "✉️",
    category: "chat",
    kind: "agent",
    agentName: "email",
    setup: {
      what: "Доступ к почтовому ящику",
      steps: [
        "Открой Настройки KALI → раздел «Почта»",
        "Укажи адрес и пароль приложения (не основной пароль!)",
        "Пароль приложения выдаёт твой почтовый сервис в настройках безопасности",
      ],
    },
    keywords: ["почта", "письмо", "email", "gmail"],
  },
  {
    id: "messenger-hub",
    title: "Мессенджеры",
    benefit: "Одно окно для уведомлений из разных мессенджеров",
    emoji: "💬",
    category: "chat",
    kind: "agent",
    agentName: "messenger-hub",
    setup: {
      what: "Подключение мессенджеров",
      steps: [
        "Открой Настройки KALI → «Мессенджеры»",
        "Подключи нужные: Telegram, WhatsApp — по кнопке",
      ],
    },
    keywords: ["мессенджер", "whatsapp", "чат"],
  },

  // — Документы —
  {
    id: "notion",
    title: "Notion",
    benefit: "Запишет заметки и идеи в твой Notion",
    emoji: "🗂",
    category: "docs",
    kind: "agent",
    agentName: "notion",
    setup: {
      what: "Ключ Notion (интеграция)",
      steps: [
        "Открой notion.so/my-integrations и создай интеграцию",
        "Скопируй Internal Integration Secret",
        "Вставь его в Настройках KALI → «Notion»",
      ],
      url: "https://www.notion.so/my-integrations",
    },
    keywords: ["notion", "заметки"],
  },
  {
    id: "docx",
    title: "Документы Word",
    benefit: "Создаст и отредактирует .docx: заявление, договор, письмо",
    emoji: "📄",
    category: "docs",
    kind: "skill",
    source: { sourceId: "anthropic", name: "docx" },
    keywords: ["word", "docx", "документ", "заявление"],
  },
  {
    id: "pdf",
    title: "PDF",
    benefit: "Прочитает, соберёт и заполнит PDF-файлы",
    emoji: "📕",
    category: "docs",
    kind: "skill",
    source: { sourceId: "anthropic", name: "pdf" },
    keywords: ["pdf", "файл"],
  },
  {
    id: "xlsx",
    title: "Таблицы Excel",
    benefit: "Посчитает и оформит таблицу .xlsx за тебя",
    emoji: "📈",
    category: "docs",
    kind: "skill",
    source: { sourceId: "anthropic", name: "xlsx" },
    keywords: ["excel", "таблица", "xlsx", "расчёт"],
  },
  {
    id: "pptx",
    title: "Презентации",
    benefit: "Соберёт презентацию .pptx по твоему рассказу",
    emoji: "📽",
    category: "docs",
    kind: "skill",
    source: { sourceId: "anthropic", name: "pptx" },
    keywords: ["презентация", "слайды", "pptx"],
  },
];

/** Case-insensitive search across title / benefit / keywords. */
export function searchCurated(entries: CuratedEntry[], query: string): CuratedEntry[] {
  const q = query.trim().toLowerCase();
  if (!q) return entries;
  return entries.filter((e) =>
    [e.title, e.benefit, ...(e.keywords ?? [])].some((s) =>
      s.toLowerCase().includes(q),
    ),
  );
}
