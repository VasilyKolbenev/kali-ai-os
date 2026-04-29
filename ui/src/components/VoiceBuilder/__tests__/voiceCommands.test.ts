// ui/src/components/VoiceBuilder/__tests__/voiceCommands.test.ts
import { describe, expect, it } from "vitest";
import { parseVoiceCommand, type VoiceContext } from "../voiceCommands";

describe("parseVoiceCommand — preview context", () => {
  const ctx: VoiceContext = { phase: "previewing", knownFields: ["interval", "goal", "notify_channel"] };

  it("'да' → confirm", () => {
    expect(parseVoiceCommand("да", ctx)).toEqual({ intent: "confirm" });
  });
  it("'давай ставь' → confirm (token at start)", () => {
    expect(parseVoiceCommand("давай ставь", ctx)).toEqual({ intent: "confirm" });
  });
  it("'нет, отмена' → cancel (token at start)", () => {
    expect(parseVoiceCommand("нет, отмена", ctx)).toEqual({ intent: "cancel" });
  });
  it("'не надо отменять, продолжай' → no match (cancel keyword in middle)", () => {
    expect(parseVoiceCommand("не надо отменять, продолжай", ctx)).toEqual({ intent: "unknown" });
  });
  it("'поправь интервал' → edit interval", () => {
    expect(parseVoiceCommand("поправь интервал", ctx)).toEqual({ intent: "edit", field: "interval" });
  });
  it("'измени цель' → edit goal", () => {
    expect(parseVoiceCommand("измени цель", ctx)).toEqual({ intent: "edit", field: "goal" });
  });
});

describe("parseVoiceCommand — wizard answer context", () => {
  const ctx: VoiceContext = { phase: "asking", knownFields: [] };

  it("short utterance whole-match cancel triggers cancel", () => {
    expect(parseVoiceCommand("отмена", ctx)).toEqual({ intent: "cancel" });
    expect(parseVoiceCommand("не надо", ctx)).toEqual({ intent: "cancel" });
  });
  it("long utterance with cancel substring is treated as content", () => {
    expect(
      parseVoiceCommand("не надо в телеграм отмена дай голосом", ctx),
    ).toEqual({ intent: "answer", text: "не надо в телеграм отмена дай голосом" });
  });
  it("normal answer is content", () => {
    expect(parseVoiceCommand("каждые два часа", ctx)).toEqual({
      intent: "answer",
      text: "каждые два часа",
    });
  });
});
