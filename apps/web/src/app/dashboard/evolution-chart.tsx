"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EvolutionPoint } from "@cifra/api-client";

const monthLabel = (month: string) => {
  const [year, m] = month.split("-");
  const names = [
    "jan",
    "fev",
    "mar",
    "abr",
    "mai",
    "jun",
    "jul",
    "ago",
    "set",
    "out",
    "nov",
    "dez",
  ];
  const index = Number(m) - 1;
  const name = names[index] ?? m;
  return `${name}/${year.slice(2)}`;
};

export default function EvolutionChart({ evolution }: { evolution: EvolutionPoint[] }) {
  const currencies = [...new Set(evolution.map((point) => point.currency))].sort();
  if (currencies.length === 0) {
    return <p>Sem série de evolução.</p>;
  }
  return (
    <div>
      {currencies.map((currency) => {
        const series = evolution
          .filter((point) => point.currency === currency)
          .map((point) => ({
            month: monthLabel(point.month),
            saldo: point.end_balance_cents / 100,
          }));
        return (
          <div key={currency} data-testid={`evolution-${currency}`}>
            <h3>{currency}</h3>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={series}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="month" />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey="saldo" name="Saldo final" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        );
      })}
    </div>
  );
}
