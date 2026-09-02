import { describe, expect, it } from "vitest";
import nextConfig from "../next.config";

type HeaderRule = {
  source: string;
  headers: { key: string; value: string }[];
};

async function headerRules(): Promise<HeaderRule[]> {
  if (!nextConfig.headers) {
    return [];
  }
  return (await nextConfig.headers()) as HeaderRule[];
}

async function findHeaders(key: string): Promise<string[]> {
  const values: string[] = [];
  for (const rule of await headerRules()) {
    for (const header of rule.headers) {
      if (header.key.toLowerCase() === key.toLowerCase()) {
        values.push(header.value);
      }
    }
  }
  return values;
}

async function singleHeader(key: string): Promise<string> {
  const values = await findHeaders(key);
  expect(values, `expected exactly one ${key} header`).toHaveLength(1);
  return values[0] as string;
}

describe("security headers", () => {
  it("applies one rule to every route", async () => {
    const rules = await headerRules();
    expect(rules).toHaveLength(1);
    expect(rules[0]?.source).toBe("/(.*)");
    expect(await findHeaders("X-Frame-Options")).toHaveLength(1);
    expect(await findHeaders("X-Content-Type-Options")).toHaveLength(1);
    expect(await findHeaders("Referrer-Policy")).toHaveLength(1);
    expect(await findHeaders("Permissions-Policy")).toHaveLength(1);
    expect(await findHeaders("Content-Security-Policy")).toHaveLength(1);
    expect(await findHeaders("Strict-Transport-Security")).toHaveLength(1);
  });

  it("sets X-Frame-Options DENY and nosniff", async () => {
    expect(await singleHeader("X-Frame-Options")).toBe("DENY");
    expect(await singleHeader("X-Content-Type-Options")).toBe("nosniff");
  });

  it("sets Referrer-Policy and minimal Permissions-Policy", async () => {
    expect(await singleHeader("Referrer-Policy")).toBe("same-origin");
    expect(await singleHeader("Permissions-Policy")).toBe(
      "camera=(), microphone=(), geolocation=()",
    );
  });

  it("forbids unsafe-eval and unsafe-inline scripts in production CSP", async () => {
    const csp = await singleHeader("Content-Security-Policy");
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).not.toContain("'unsafe-inline'");
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'self'");
  });

  it("sets HSTS with includeSubDomains and preload", async () => {
    expect(await singleHeader("Strict-Transport-Security")).toBe(
      "max-age=63072000; includeSubDomains; preload",
    );
  });
});
