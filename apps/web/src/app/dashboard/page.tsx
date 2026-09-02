import { redirect } from "next/navigation";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { createApiClient } from "@cifra/api-client";
import type { DashboardSummary, EvolutionPoint, MonthComparison } from "@cifra/api-client";

const apiBaseUrl =
  process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{ token?: string }>;

const brl = (cents: number, currency: string) =>
  (cents / 100).toLocaleString("pt-BR", { style: "currency", currency });

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

const typeLabel = (operationType: string) =>
  operationType === "deposit"
    ? "entrada"
    : operationType === "withdrawal"
      ? "saída"
      : operationType;

type DashboardData = {
  summary: DashboardSummary;
  evolution: EvolutionPoint[];
  comparison: MonthComparison;
};

function DashboardError() {
  return (
    <section>
      <h1>Dashboard</h1>
      <p role="alert">Não foi possível carregar o dashboard.</p>
    </section>
  );
}

async function loadDashboard(token: string): Promise<{ data: DashboardData | null }> {
  const api = createApiClient({ baseUrl: apiBaseUrl });
  try {
    const summary = await api.dashboardSummary(token);
    const [evolution, comparison] = await Promise.all([
      api.dashboardEvolution(token, 6, summary.month),
      api.dashboardMonthComparison(token, summary.month),
    ]);
    return { data: { summary, evolution, comparison } };
  } catch {
    return { data: null };
  }
}

function BalanceBlocks({ summary }: { summary: DashboardSummary }) {
  if (summary.consolidated_by_currency.length === 0) {
    return <p>Nenhuma conta cadastrada.</p>;
  }
  return (
    <ul>
      {summary.consolidated_by_currency.map((item) => (
        <li key={item.currency} data-testid={`currency-${item.currency}`}>
          <span>{item.currency}</span>
          <span>{brl(item.posted_balance_cents, item.currency)}</span>
          <span>projetado: {brl(item.projected_balance_cents, item.currency)}</span>
        </li>
      ))}
    </ul>
  );
}

function AccountsTable({ summary }: { summary: DashboardSummary }) {
  if (summary.accounts.length === 0) {
    return <p>Nenhuma conta para exibir.</p>;
  }
  return (
    <table>
      <caption className="sr-only">Saldo por conta</caption>
      <thead>
        <tr>
          <th scope="col">Conta</th>
          <th scope="col">Moeda</th>
          <th scope="col">Saldo</th>
          <th scope="col">Projetado</th>
        </tr>
      </thead>
      <tbody>
        {summary.accounts.map((account) => (
          <tr key={account.account_id}>
            <td>{account.name}</td>
            <td>{account.currency}</td>
            <td>{brl(account.posted_balance_cents, account.currency)}</td>
            <td>{brl(account.projected_balance_cents, account.currency)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function MonthFlowSection({ summary }: { summary: DashboardSummary }) {
  if (summary.month_flow.length === 0) {
    return <p>Nenhum fluxo no mês.</p>;
  }
  return (
    <ul>
      {summary.month_flow.map((flow) => (
        <li key={flow.currency} data-testid={`flow-${flow.currency}`}>
          <span>{flow.currency}</span>
          <span>Entradas: {brl(flow.income_cents, flow.currency)}</span>
          <span>Saídas: {brl(flow.expense_cents, flow.currency)}</span>
          <span>Fluxo do mês: {brl(flow.net_cents, flow.currency)}</span>
        </li>
      ))}
    </ul>
  );
}

function UpcomingSection({ summary }: { summary: DashboardSummary }) {
  if (summary.upcoming.length === 0) {
    return <p>Nenhum lançamento agendado.</p>;
  }
  return (
    <ul>
      {summary.upcoming.map((item) => (
        <li key={item.id}>
          <span>{brl(item.amount_cents, "BRL")}</span>
          <span>{typeLabel(item.operation_type)}</span>
          <time dateTime={item.occurred_at}>
            {new Date(item.occurred_at).toLocaleDateString("pt-BR")}
          </time>
          {item.description === null ? null : <span>{item.description}</span>}
        </li>
      ))}
    </ul>
  );
}

function RecentSection({ summary }: { summary: DashboardSummary }) {
  if (summary.recent.length === 0) {
    return <p>Nenhum lançamento registrado.</p>;
  }
  return (
    <ul>
      {summary.recent.map((item) => (
        <li key={item.id}>
          <span>{brl(item.amount_cents, "BRL")}</span>
          <span>{typeLabel(item.operation_type)}</span>
          <span>{item.status}</span>
          <time dateTime={item.occurred_at}>
            {new Date(item.occurred_at).toLocaleDateString("pt-BR")}
          </time>
          {item.description === null ? null : <span>{item.description}</span>}
        </li>
      ))}
    </ul>
  );
}

function EvolutionChart({ evolution }: { evolution: EvolutionPoint[] }) {
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

function ComparisonSection({ comparison }: { comparison: MonthComparison }) {
  if (comparison.rows.length === 0) {
    return <p>Sem comparativo para o mês.</p>;
  }
  return (
    <table>
      <caption className="sr-only">Comparativo mês a mês</caption>
      <thead>
        <tr>
          <th scope="col">Moeda</th>
          <th scope="col">Entradas</th>
          <th scope="col">Saídas</th>
          <th scope="col">Fluxo</th>
          <th scope="col">Variação do fluxo</th>
        </tr>
      </thead>
      <tbody>
        {comparison.rows.map((row) => (
          <tr key={row.currency} data-testid={`comparison-${row.currency}`}>
            <td>{row.currency}</td>
            <td>{brl(row.current_income_cents, row.currency)}</td>
            <td>{brl(row.current_expense_cents, row.currency)}</td>
            <td>{brl(row.current_net_cents, row.currency)}</td>
            <td>{brl(row.delta_net_cents, row.currency)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default async function DashboardPage({ searchParams }: { searchParams: SearchParams }) {
  const { token } = await searchParams;
  if (!token) {
    redirect("/");
  }

  const { data } = await loadDashboard(token);
  if (data === null) {
    return <DashboardError />;
  }

  const { summary, evolution, comparison } = data;

  return (
    <main>
      <section>
        <h1>Dashboard</h1>
        <p>
          Mês de referência: <strong>{summary.month}</strong>
        </p>
        <h2>Saldos consolidados</h2>
        <BalanceBlocks summary={summary} />
        <h2>Fluxo do mês</h2>
        <MonthFlowSection summary={summary} />
        <h2>Contas</h2>
        <AccountsTable summary={summary} />
      </section>
      <section>
        <h2>Próximos agendados</h2>
        <UpcomingSection summary={summary} />
        <h2>Últimos lançamentos</h2>
        <RecentSection summary={summary} />
      </section>
      <section>
        <h2>Evolução mensal</h2>
        <EvolutionChart evolution={evolution} />
        <h2>Comparativo mês a mês</h2>
        <ComparisonSection comparison={comparison} />
      </section>
    </main>
  );
}
