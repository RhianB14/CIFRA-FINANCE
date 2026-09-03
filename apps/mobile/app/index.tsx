import { createApiClient } from "@cifra/api-client";
import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, FlatList, StyleSheet, Text, View } from "react-native";

const apiBaseUrl = globalThis.process?.env.EXPO_PUBLIC_API_URL ?? "http://localhost:18000";
const sessionValue = globalThis.process?.env.EXPO_PUBLIC_ACCESS_TOKEN;

export default function HomeScreen() {
  const api = useMemo(() => createApiClient({ baseUrl: apiBaseUrl }), []);
  const [cards, setCards] = useState<Awaited<ReturnType<typeof api.listCards>>>([]);
  const [loading, setLoading] = useState(Boolean(sessionValue));
  const [error, setError] = useState(
    sessionValue ? "" : "Entre na sua conta para visualizar os cartões.",
  );

  useEffect(() => {
    if (!sessionValue) return;
    api
      .listCards(sessionValue)
      .then(setCards)
      .catch(() => setError("Não foi possível carregar os cartões."))
      .finally(() => setLoading(false));
  }, [api]);

  return (
    <View style={styles.container}>
      <Text style={styles.title} accessibilityRole="header">
        Cartões
      </Text>
      <Text style={styles.subtitle}>Faturas, compras, parcelas e pagamentos online.</Text>
      {loading ? (
        <ActivityIndicator color="#6be0b7" accessibilityLabel="Carregando cartões" />
      ) : null}
      {error ? (
        <Text style={styles.error} accessibilityLiveRegion="polite">
          {error}
        </Text>
      ) : null}
      {!loading && !error && cards.length === 0 ? (
        <Text style={styles.empty}>Nenhum cartão cadastrado.</Text>
      ) : null}
      <FlatList
        data={cards}
        keyExtractor={(card) => card.id}
        renderItem={({ item }) => (
          <View style={styles.card} accessibilityLabel={`Cartão ${item.name}`}>
            <Text style={styles.cardTitle}>{item.name}</Text>
            <Text style={styles.value}>
              {(item.limit_cents / 100).toLocaleString("pt-BR", {
                style: "currency",
                currency: item.currency,
              })}
            </Text>
            <Text style={styles.meta}>
              Fecha dia {item.closing_day} · vence dia {item.due_day}
            </Text>
            <Text style={styles.meta}>
              {item.last_four ? `Final ${item.last_four}` : "Número não armazenado"}
            </Text>
            {item.archived_at ? <Text style={styles.archived}>Arquivado</Text> : null}
          </View>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  archived: { color: "#f5b35c", marginTop: 8 },
  card: {
    backgroundColor: "#10271f",
    borderColor: "#2c6152",
    borderRadius: 18,
    borderWidth: 1,
    marginBottom: 16,
    padding: 20,
  },
  cardTitle: { color: "#f2f7f5", fontSize: 22, fontWeight: "700" },
  container: { backgroundColor: "#08120f", flex: 1, padding: 24, paddingTop: 64 },
  empty: { color: "#b4cbc3", fontSize: 16, marginTop: 32 },
  error: { color: "#ff9c9c", fontSize: 16, marginTop: 24 },
  meta: { color: "#b4cbc3", marginTop: 6 },
  subtitle: { color: "#b4cbc3", fontSize: 16, marginBottom: 28, marginTop: 8 },
  title: { color: "#f2f7f5", fontSize: 40, fontWeight: "700" },
  value: { color: "#6be0b7", fontSize: 20, fontWeight: "600", marginTop: 14 },
});
