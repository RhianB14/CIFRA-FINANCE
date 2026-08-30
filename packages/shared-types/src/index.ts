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
