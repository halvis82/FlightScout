import {
  pgTable,
  text,
  timestamp,
  boolean,
  integer,
  doublePrecision,
  jsonb,
  date,
  index,
  uniqueIndex,
  serial,
  primaryKey,
} from "drizzle-orm/pg-core";

// ---------------------------------------------------------------------------
// Better Auth tables (names and columns follow Better Auth's defaults)
// ---------------------------------------------------------------------------

export const user = pgTable("user", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  email: text("email").notNull().unique(),
  emailVerified: boolean("email_verified").notNull().default(false),
  image: text("image"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const session = pgTable(
  "session",
  {
    id: text("id").primaryKey(),
    expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
    token: text("token").notNull().unique(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
    ipAddress: text("ip_address"),
    userAgent: text("user_agent"),
    userId: text("user_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
  },
  (t) => [index("session_user_idx").on(t.userId)],
);

export const account = pgTable(
  "account",
  {
    id: text("id").primaryKey(),
    accountId: text("account_id").notNull(),
    providerId: text("provider_id").notNull(),
    userId: text("user_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    accessToken: text("access_token"),
    refreshToken: text("refresh_token"),
    idToken: text("id_token"),
    accessTokenExpiresAt: timestamp("access_token_expires_at", { withTimezone: true }),
    refreshTokenExpiresAt: timestamp("refresh_token_expires_at", { withTimezone: true }),
    scope: text("scope"),
    password: text("password"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("account_user_idx").on(t.userId)],
);

export const verification = pgTable("verification", {
  id: text("id").primaryKey(),
  identifier: text("identifier").notNull(),
  value: text("value").notNull(),
  expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const passkey = pgTable(
  "passkey",
  {
    id: text("id").primaryKey(),
    name: text("name"),
    publicKey: text("public_key").notNull(),
    userId: text("user_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    credentialID: text("credential_id").notNull(),
    counter: integer("counter").notNull(),
    deviceType: text("device_type").notNull(),
    backedUp: boolean("backed_up").notNull(),
    transports: text("transports"),
    createdAt: timestamp("created_at", { withTimezone: true }),
    aaguid: text("aaguid"),
  },
  (t) => [index("passkey_user_idx").on(t.userId), index("passkey_cred_idx").on(t.credentialID)],
);

// ---------------------------------------------------------------------------
// FlightScout tables
// ---------------------------------------------------------------------------

export type PlannerDefaults = {
  max_stopover_days: number;
  min_connection_hours: number;
  max_trip_days: number | null;
  max_hubs: number;
  allow_self_transfer: boolean;
  include_nested_roundtrips: boolean;
};

export type SellerRule = { seller: string; mode: "block" | "warn"; note?: string };

export const settings = pgTable("settings", {
  userId: text("user_id")
    .primaryKey()
    .references(() => user.id, { onDelete: "cascade" }),
  currency: text("currency").notNull().default("USD"),
  defaultOrigins: text("default_origins").array().notNull().default([]),
  planner: jsonb("planner").$type<PlannerDefaults>(),
  sellerRules: jsonb("seller_rules").$type<SellerRule[]>().notNull().default([]),
  emailAlerts: boolean("email_alerts").notNull().default(false),
  pushAlerts: boolean("push_alerts").notNull().default(false),
  onboarded: boolean("onboarded").notNull().default(false),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const places = pgTable(
  "places",
  {
    id: serial("id").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    label: text("label").notNull(),
    codes: text("codes").array().notNull(),
    kind: text("kind").$type<"home" | "frequent" | "interested">().notNull().default("frequent"),
    signature: text("signature"), // sorted codes; unique per user
    color: text("color"),
    notes: text("notes"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("places_user_idx").on(t.userId), uniqueIndex("places_user_sig_idx").on(t.userId, t.signature)],
);

export type WatchLeg = {
  origins: string[];
  destinations: string[];
  date: string;
  before?: number;
  after?: number;
  arrive_by?: string | null;
};

export const watches = pgTable(
  "watches",
  {
    id: serial("id").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    name: text("name").notNull(),
    origins: text("origins").array().notNull(),
    destinations: text("destinations").array().notNull(),
    tripType: text("trip_type").$type<"oneway" | "roundtrip" | "multicity">().notNull().default("roundtrip"),
    // multi city watches: [{origins, destinations, date, before, after, arrive_by}]
    legs: jsonb("legs").$type<WatchLeg[] | null>(),
    // identity of the search (route, dates, trip length, cabin, passengers);
    // unique per user so double clicks and retries can't create duplicates
    signature: text("signature"),
    departStart: date("depart_start").notNull(),
    departEnd: date("depart_end").notNull(),
    nightsMin: integer("nights_min"),
    nightsMax: integer("nights_max"),
    cabin: text("cabin").notNull().default("economy"),
    adults: integer("adults").notNull().default(1),
    maxStops: integer("max_stops"),
    currency: text("currency").notNull().default("USD"),
    includeSplit: boolean("include_split").notNull().default(false),
    alertBelow: doublePrecision("alert_below"),
    alertDropPct: doublePrecision("alert_drop_pct"),
    active: boolean("active").notNull().default(true),
    lastCheckedAt: timestamp("last_checked_at", { withTimezone: true }),
    // current best (latest check), the one before it, and all time low, all in watch currency
    bestPrice: doublePrecision("best_price"),
    prevPrice: doublePrecision("prev_price"),
    lowestPrice: doublePrecision("lowest_price"),
    bestTrip: jsonb("best_trip"),
    notes: text("notes"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("watches_user_idx").on(t.userId), uniqueIndex("watches_user_sig_idx").on(t.userId, t.signature)],
);

export const observations = pgTable(
  "observations",
  {
    id: serial("id").primaryKey(),
    watchId: integer("watch_id")
      .notNull()
      .references(() => watches.id, { onDelete: "cascade" }),
    observedAt: timestamp("observed_at", { withTimezone: true }).notNull().defaultNow(),
    departDate: date("depart_date").notNull(),
    returnDate: date("return_date"),
    price: doublePrecision("price").notNull(),
    currency: text("currency").notNull(),
    priceUsd: doublePrecision("price_usd"),
    source: text("source").notNull(),
    kind: text("kind").notNull().default("single"),
    route: text("route"),
    durationMin: integer("duration_min"),
    bookingUrl: text("booking_url"),
    trip: jsonb("trip"),
  },
  (t) => [
    index("obs_watch_time_idx").on(t.watchId, t.observedAt),
    index("obs_watch_depart_idx").on(t.watchId, t.departDate),
  ],
);

export const searches = pgTable(
  "searches",
  {
    id: serial("id").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    kind: text("kind").$type<"search" | "plan" | "explore" | "dates" | "trip" | "multicity">().notNull(),
    origin: text("origin").$type<"web" | "cli" | "mcp" | "tracker" | "local">().notNull().default("web"),
    summary: text("summary"),
    query: jsonb("query").notNull(),
    payload: jsonb("payload"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("searches_user_time_idx").on(t.userId, t.createdAt)],
);

export const apiTokens = pgTable(
  "api_tokens",
  {
    id: serial("id").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    name: text("name").notNull(),
    tokenHash: text("token_hash").notNull(),
    prefix: text("prefix").notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    lastUsedAt: timestamp("last_used_at", { withTimezone: true }),
  },
  (t) => [uniqueIndex("api_tokens_hash_idx").on(t.tokenHash)],
);

export const pushSubscriptions = pgTable(
  "push_subscriptions",
  {
    id: serial("id").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    endpoint: text("endpoint").notNull(),
    p256dh: text("p256dh").notNull(),
    auth: text("auth").notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [uniqueIndex("push_endpoint_idx").on(t.endpoint)],
);

export const alerts = pgTable(
  "alerts",
  {
    id: serial("id").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    watchId: integer("watch_id").references(() => watches.id, { onDelete: "cascade" }),
    message: text("message").notNull(),
    price: doublePrecision("price"),
    currency: text("currency"),
    bookingUrl: text("booking_url"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    readAt: timestamp("read_at", { withTimezone: true }),
  },
  (t) => [index("alerts_user_idx").on(t.userId, t.createdAt)],
);

// Fixed window rate limit counters for engine calls (per IP for guests, per
// user when signed in). Old windows are removed by the cleanup cron.
export const rateLimits = pgTable(
  "rate_limits",
  {
    key: text("key").notNull(),
    windowStart: timestamp("window_start", { withTimezone: true }).notNull(),
    count: integer("count").notNull().default(0),
  },
  (t) => [uniqueIndex("rate_limits_key_window_idx").on(t.key, t.windowStart)],
);

// Shared explore results per origin, warmed by the tracker (Google Explore in
// a real browser + Kiwi) so explore on the site can show results instantly.
export const exploreCache = pgTable("explore_cache", {
  origin: text("origin").primaryKey(),
  currency: text("currency").notNull(),
  items: jsonb("items").notNull(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

// Shared engine results: the same search by anyone within a few minutes is
// answered from here instead of asking Google (and friends) again.
export const searchCache = pgTable("search_cache", {
  key: text("key").primaryKey(),
  kind: text("kind").notNull(),
  payload: jsonb("payload").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

// The cheapest one way price seen per route and day (USD), from every saved
// result, CLI push and tracker check. Smart routes use it to pick layovers
// ("Rome to Oslo was 46 USD yesterday") without asking any site.
export const fareMemory = pgTable(
  "fare_memory",
  {
    origin: text("origin").notNull(),
    dest: text("dest").notNull(),
    day: date("day").notNull(),
    usd: doublePrecision("usd").notNull(),
    seenAt: timestamp("seen_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [primaryKey({ columns: [t.origin, t.dest, t.day] }), index("fare_memory_dest").on(t.dest, t.day)],
);
