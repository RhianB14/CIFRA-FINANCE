import { createApiClient } from "@cifra/api-client";
import { render } from "@testing-library/react-native";

import HomeScreen from "./index";

jest.mock("@cifra/api-client", () => ({
  createApiClient: jest.fn(() => ({ listCards: jest.fn() })),
}));

const mockCreateApiClient = jest.mocked(createApiClient);

describe("HomeScreen", () => {
  beforeEach(() => {
    mockCreateApiClient.mockClear();
  });

  it("renders the online cards screen", async () => {
    const view = await render(<HomeScreen />);

    expect(view.getByText("Cartões")).toBeTruthy();
    expect(view.getByText("Entre na sua conta para visualizar os cartões.")).toBeTruthy();
  });

  it("configures the API client without a token request", async () => {
    await render(<HomeScreen />);

    expect(mockCreateApiClient).toHaveBeenCalledTimes(1);
    expect(mockCreateApiClient).toHaveBeenCalledWith({ baseUrl: "http://10.0.2.2:8000" });
  });
});
