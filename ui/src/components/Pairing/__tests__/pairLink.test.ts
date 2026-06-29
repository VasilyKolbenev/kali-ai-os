import { describe, it, expect } from "vitest";
import { buildPairLink } from "../pairLink";

describe("buildPairLink", () => {
  it("builds a kali://pair link with bare ip + token", () => {
    expect(buildPairLink("192.168.1.42", "abc123")).toBe(
      "kali://pair?ip=192.168.1.42&token=abc123",
    );
  });

  it("url-encodes the token", () => {
    const link = buildPairLink("10.0.0.5", "a+b/c=d");
    // URLSearchParams encodes +, /, = inside the value.
    expect(link).toContain("ip=10.0.0.5");
    expect(link).toContain("token=a%2Bb%2Fc%3Dd");
    expect(link).not.toContain("token=a+b/c=d");
  });

  it("does NOT embed a port (mobile appends :3006 itself)", () => {
    expect(buildPairLink("192.168.1.42", "tok")).not.toContain(":3006");
  });
});
