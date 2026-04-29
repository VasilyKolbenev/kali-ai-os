import { beforeEach, describe, expect, it, vi } from "vitest";
import { useBuilderStore } from "../builder";

vi.mock("../../api/builder", () => ({
  builderApi: {
    extract: vi.fn(),
    start: vi.fn(),
    answer: vi.fn(),
    deploy: vi.fn(),
    cancel: vi.fn(),
    transcribe: vi.fn(),
    say: vi.fn(),
  },
}));

describe("useBuilderStore phases", () => {
  beforeEach(() => {
    useBuilderStore.getState().reset();
  });

  it("starts in idle", () => {
    expect(useBuilderStore.getState().phase).toBe("idle");
  });

  it("transitions through listening → transcribing → extracting on submitAudio", async () => {
    const { builderApi } = await import("../../api/builder");
    (builderApi.transcribe as ReturnType<typeof vi.fn>).mockResolvedValue({
      text: "трекер воды",
      language: "ru",
      duration_ms: 100,
    });
    (builderApi.extract as ReturnType<typeof vi.fn>).mockResolvedValue({
      complete: false,
      session_id: "sid1",
      step: 0,
      total_steps: 3,
      next_question: "Какая дневная цель?",
      partial_spec: { name: "treker-vody", template: "tracker", config: {} },
    });

    const phases: string[] = [];
    const unsub = useBuilderStore.subscribe((s) => phases.push(s.phase));

    useBuilderStore.getState().tap();
    expect(useBuilderStore.getState().phase).toBe("listening");

    const fakeBlob = new Uint8Array([0, 0, 0, 0]);
    await useBuilderStore.getState().submitAudio(fakeBlob, 16000);

    unsub();
    expect(phases).toContain("transcribing");
    expect(phases).toContain("extracting");
    expect(useBuilderStore.getState().phase).toBe("asking");
    expect(useBuilderStore.getState().sessionId).toBe("sid1");
  });

  it("complete=true skips wizard and lands on previewing", async () => {
    const { builderApi } = await import("../../api/builder");
    (builderApi.transcribe as ReturnType<typeof vi.fn>).mockResolvedValue({
      text: "трекер 2 литра 2 часа в чат",
      language: "ru",
      duration_ms: 100,
    });
    (builderApi.extract as ReturnType<typeof vi.fn>).mockResolvedValue({
      complete: true,
      session_id: "sid2",
      spec: {
        name: "treker-vody",
        template: "tracker",
        description: "...",
        type: "skill",
        config: { interval: "2 часа", goal: "2 литра", notify_channel: "чат" },
      },
    });

    const fakeBlob = new Uint8Array([0, 0, 0, 0]);
    await useBuilderStore.getState().submitAudio(fakeBlob, 16000);

    expect(useBuilderStore.getState().phase).toBe("previewing");
    expect(useBuilderStore.getState().preview?.name).toBe("treker-vody");
  });

  it("tap during listening cancels back to idle", () => {
    useBuilderStore.getState().tap();
    expect(useBuilderStore.getState().phase).toBe("listening");
    useBuilderStore.getState().tap();
    expect(useBuilderStore.getState().phase).toBe("idle");
  });
});
