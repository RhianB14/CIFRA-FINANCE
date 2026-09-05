export type LiveStatus = {
  status: "alive";
  service: string;
};

export type DependencyName = "postgres" | "redis" | "storage";
export type DependencyStatus = "healthy" | "unhealthy";

export type ReadyStatus = {
  status: "ready" | "not_ready";
  dependencies: Record<DependencyName, DependencyStatus>;
};

export type CreditCardStatus = "active" | "archived";
export type CardInvoiceStatus = "open" | "closed" | "partially_paid" | "paid" | "overdue";
export type CardChargeKind =
  "purchase" | "interest" | "late_fee" | "iof" | "withdrawal_fee" | "other";

export const CARD_CHARGE_LABELS: Record<CardChargeKind, string> = {
  purchase: "Compra",
  interest: "Juros",
  late_fee: "Multa por atraso",
  iof: "IOF",
  withdrawal_fee: "Tarifa de saque",
  other: "Outro",
};
