import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const live = vi.fn();

vi.mock("@cifra/api-client", () => ({
  createApiClient: () => ({ live }),
}));

describe("Home", () => {
  afterEach(() => {
    live.mockReset();
  });

  it("renders the foundation when the API is operational", async () => {
    live.mockResolvedValue({ status: "alive", service: "cifra-api" });
    const { default: Home } = await import("./page");

    render(await Home());

    expect(screen.getByRole("heading", { name: "Cifra" })).toBeTruthy();
    expect(screen.getByText("operacional")).toBeTruthy();
  });

  it("renders a stable fallback when the API is unavailable", async () => {
    live.mockRejectedValue(new Error("unavailable"));
    const { default: Home } = await import("./page");

    render(await Home());

    expect(screen.getByText("indisponível")).toBeTruthy();
  });
});
