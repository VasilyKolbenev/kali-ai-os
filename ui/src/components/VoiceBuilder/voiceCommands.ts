// ui/src/components/VoiceBuilder/voiceCommands.ts
const CONFIRM_WORDS = ["да", "давай", "ставь", "запускай", "поехали", "ок", "подтверди"];
const CANCEL_WORDS = ["отмена", "не надо", "хватит", "перестань", "стоп", "отменяй", "нет"];
const EDIT_PREFIXES = ["поправь", "измени", "переделай"];

const FIELD_KEYWORDS: Record<string, string[]> = {
  interval: ["интервал", "часто", "часов", "раз"],
  goal: ["цель", "цел"],
  notify_channel: ["уведом", "куда", "канал"],
  time_window: ["время"],
  target: ["url", "сервис", "адрес"],
  trigger: ["условие"],
  categories: ["категори", "событи"],
};

export type VoiceContext = {
  phase: "previewing" | "asking";
  knownFields: string[];
};

export type VoiceCommand =
  | { intent: "confirm" }
  | { intent: "cancel" }
  | { intent: "edit"; field: string }
  | { intent: "answer"; text: string }
  | { intent: "unknown" };

const _tokens = (s: string): string[] =>
  s
    .toLowerCase()
    .replace(/[.,!?;:«»"—–…­]/g, " ")
    .split(/\s+/)
    .filter(Boolean);

const _hasNearEdge = (toks: string[], words: string[]): boolean => {
  // Whole-token equality (not substring) prevents false positives like
  // "нетронутый" → "нет" → cancel, or "стоплосс" → "стоп" → cancel.
  const head = toks.slice(0, 3);
  const tail = toks.slice(-3);
  return words.some((w) =>
    head.includes(w) || tail.includes(w),
  );
};

export function parseVoiceCommand(text: string, ctx: VoiceContext): VoiceCommand {
  const toks = _tokens(text);
  if (toks.length === 0) return { intent: "unknown" };

  if (ctx.phase === "previewing") {
    if (_hasNearEdge(toks, CONFIRM_WORDS)) return { intent: "confirm" };
    if (_hasNearEdge(toks, CANCEL_WORDS)) return { intent: "cancel" };
    // Edit: look for "поправь <field>" / "измени <field>" / "<field>"
    for (let i = 0; i < toks.length; i++) {
      if (EDIT_PREFIXES.some((p) => toks[i].includes(p)) && i + 1 < toks.length) {
        const candidate = toks[i + 1];
        for (const [field, kws] of Object.entries(FIELD_KEYWORDS)) {
          if (
            ctx.knownFields.includes(field) &&
            kws.some((k) => candidate.includes(k))
          ) {
            return { intent: "edit", field };
          }
        }
      }
    }
    return { intent: "unknown" };
  }

  // ctx.phase === "asking" — wizard answer
  if (toks.length <= 3) {
    const joined = toks.join(" ");
    if (CANCEL_WORDS.some((c) => joined === c || joined === c.replace(" ", ""))) {
      return { intent: "cancel" };
    }
  }
  return { intent: "answer", text };
}
