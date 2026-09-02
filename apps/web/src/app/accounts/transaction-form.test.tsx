import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import TransactionForm from "./transaction-form";

const createTransaction = vi.fn();

vi.mock("@cifra/api-client", () => ({
  createApiClient: () => ({
    createTransaction: (...args: unknown[]) => createTransaction(...args),
  }),
}));

describe("TransactionForm", () => {
  beforeEach(() => {
    createTransaction.mockReset();
  });

  it("blocks submission when fields are missing", async () => {
    render(<TransactionForm token="t" accountId="a1" currency="BRL" />);
    fireEvent.click(screen.getByRole("button", { name: /lançar/i }));
    await waitFor(() => {
      expect(createTransaction).not.toHaveBeenCalled();
      expect(screen.getAllByText(/obrigatório/i).length).toBeGreaterThan(0);
    });
  });

  it("submits and renders the balance returned by the api", async () => {
    createTransaction.mockResolvedValue({
      current_balance_cents: 118000,
      projected_balance_cents: 118000,
    });
    render(<TransactionForm token="t" accountId="a1" currency="BRL" />);
    fireEvent.change(screen.getByLabelText(/valor/i), { target: { value: "50,00" } });
    fireEvent.change(screen.getByLabelText(/descrição/i), { target: { value: "Depósito" } });
    fireEvent.click(screen.getByRole("button", { name: /lançar/i }));
    await waitFor(() => {
      expect(createTransaction).toHaveBeenCalledWith(
        "t",
        "a1",
        expect.objectContaining({ amount_cents: 5000, operation_type: "deposit" }),
      );
      expect(screen.getByText(/novo saldo/i)).toHaveTextContent("R$ 1.180,00");
    });
  });
});
