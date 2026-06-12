import { describe, it, expect } from "vitest";
import { CATEGORIES, CURATED, searchCurated } from "../curated";

describe("searchCurated", () => {
  it("returns all entries for an empty query", () => {
    expect(searchCurated(CURATED, "")).toHaveLength(CURATED.length);
    expect(searchCurated(CURATED, "   ")).toHaveLength(CURATED.length);
  });

  it("matches by title", () => {
    const hits = searchCurated(CURATED, "Погода");
    expect(hits.some((e) => e.id === "weather")).toBe(true);
  });

  it("matches by benefit substring", () => {
    const hits = searchCurated(CURATED, "прогноз");
    expect(hits.some((e) => e.id === "weather")).toBe(true);
  });

  it("matches by keyword synonym", () => {
    const hits = searchCurated(CURATED, "дождь");
    expect(hits.some((e) => e.id === "weather")).toBe(true);
  });

  it("is case-insensitive", () => {
    const hits = searchCurated(CURATED, "ПОГОДА");
    expect(hits.some((e) => e.id === "weather")).toBe(true);
  });
});

describe("CURATED data integrity", () => {
  const categoryIds = new Set(CATEGORIES.map((c) => c.id));

  it("agent entries reference an agent name; skill entries a source ref", () => {
    for (const entry of CURATED) {
      if (entry.kind === "agent") {
        expect(entry.agentName, entry.id).toBeTruthy();
      } else {
        expect(entry.source?.sourceId, entry.id).toBeTruthy();
        expect(entry.source?.name, entry.id).toBeTruthy();
      }
    }
  });

  it("every entry belongs to a known category (not 'all')", () => {
    for (const entry of CURATED) {
      expect(categoryIds.has(entry.category), entry.id).toBe(true);
      expect(entry.category).not.toBe("all");
    }
  });

  it("entries with setup guidance have non-empty steps", () => {
    for (const entry of CURATED) {
      if (entry.setup) {
        expect(entry.setup.steps.length, entry.id).toBeGreaterThan(0);
        expect(entry.setup.what, entry.id).toBeTruthy();
      }
    }
  });
});
