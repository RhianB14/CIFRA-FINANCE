import { createApiClient } from "@cifra/api-client";

const apiBaseUrl =
  process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default async function Home() {
  const api = createApiClient({ baseUrl: apiBaseUrl });
  const apiStatus = await api
    .live()
    .then((health) => (health.status === "alive" ? "operacional" : "indisponível"))
    .catch(() => "indisponível");

  return (
    <main>
      <section>
        <h1>Cifra</h1>
        <p>Fundação do seu controle financeiro pessoal.</p>
        <p>
          API: <strong>{apiStatus}</strong>
        </p>
      </section>
    </main>
  );
}
