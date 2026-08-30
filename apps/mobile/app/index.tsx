import { createApiClient } from "@cifra/api-client";
import { StyleSheet, Text, View } from "react-native";

const apiBaseUrl = process.env.EXPO_PUBLIC_API_URL ?? "http://10.0.2.2:8000";

export default function HomeScreen() {
  const api = createApiClient({ baseUrl: apiBaseUrl });

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Cifra</Text>
      <Text style={styles.subtitle}>Controle financeiro pessoal confiável.</Text>
      <Text style={styles.foundation}>Fundação mobile preparada</Text>
      <Text style={styles.client}>{api.live.name ? "Cliente da API configurado" : ""}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: "center",
    backgroundColor: "#08120f",
    flex: 1,
    justifyContent: "center",
    padding: 32,
  },
  title: {
    color: "#f2f7f5",
    fontSize: 64,
    fontWeight: "700",
    letterSpacing: -4,
  },
  subtitle: {
    color: "#b4cbc3",
    fontSize: 18,
    marginTop: 16,
    textAlign: "center",
  },
  foundation: {
    color: "#6be0b7",
    fontSize: 16,
    marginTop: 32,
  },
  client: {
    color: "#7f9c92",
    fontSize: 14,
    marginTop: 12,
  },
});
