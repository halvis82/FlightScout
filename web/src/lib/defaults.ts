import type { PlannerDefaults } from "./db/schema";

export const DEFAULT_PLANNER: PlannerDefaults = {
  max_stopover_days: 3,
  min_connection_hours: 3,
  max_trip_days: null,
  max_hubs: 10,
  allow_self_transfer: true,
  include_nested_roundtrips: true,
};
