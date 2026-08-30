import { createApiClient } from "@cifra/api-client";
import { render } from "@testing-library/react-native";

import HomeScreen from "./index";

jest.mock("@cifra/api-client", () => ({
  createApiClient: jest.fn(() => ({ live: jest.fn(), ready: jest.fn() })),
}));

const mockCreateApiClient = jest.mocked(createApiClient);

describe("HomeScreen", () => {
  beforeEach(() => {
    mockCreateApiClient.mockClear();
  });

  it("renders Cifra", async () => {
    const view = await render(<HomeScreen />);

    expect(view.getByText("Cifra")).toBeTruthy();
  });

  it("configures the API client without a network request", async () => {
    const view = await render(<HomeScreen />);

    expect(mockCreateApiClient).toHaveBeenCalledTimes(1);
    expect(mockCreateApiClient).toHaveBeenCalledWith({ baseUrl: "http://10.0.2.2:8000" });
    expect(view.getByText("Cliente da API configurado")).toBeTruthy();
  });
});
