// JSON shapes produced by the engine (engine/src/flightscout/models.py).

export type Source = "google" | "kiwi" | "ryanair" | "serpapi" | "volaris" | (string & {});
export type Cabin = "economy" | "premium" | "business" | "first";

export interface Segment {
  origin: string;
  destination: string;
  departure: string;
  arrival: string;
  carrier: string;
  carrier_name?: string | null;
  flight_number?: string | null;
  duration_min?: number | null;
  aircraft?: string | null;
}

export interface Slice {
  segments: Segment[];
  duration_min: number;
  origin: string;
  destination: string;
  departure: string;
  arrival: string;
  stops: number;
  carriers: string[];
}

export interface Fare {
  name?: string | null;
  price: number;
  features: string[];
}

export interface Offer {
  seller: string;
  is_airline: boolean;
  fares: Fare[];
}

export interface Itinerary {
  id: string;
  source: Source;
  price: number;
  currency: string;
  slices: Slice[];
  booking_url: string;
  seller?: string | null;
  seller_kind: "airline" | "ota" | "metasearch";
  self_transfer: boolean;
  return_pending?: boolean; // round trip priced by Google, return chosen on the booking page
  baggage?: Record<string, number> | null;
  offers?: Offer[] | null;
  price_insight?: string | null;
  warnings: string[];
  fetched_at: string;
  trip_type: "oneway" | "roundtrip" | "multi";
}

export type TripKind = "single" | "split" | "stopover" | "nested" | "multicity";

export interface Trip {
  id: string;
  tickets: Itinerary[];
  total_price: number;
  currency: string;
  kind: TripKind;
  stopovers: { airport: string; hours: number }[];
  risks: string[];
  savings_vs_direct?: number | null;
  score?: number | null;
  route: string[];
  departure: string;
  arrival: string;
  travel_min: number;
}

export interface DatePrice {
  origin: string;
  destination: string;
  departure: string;
  return_date?: string | null;
  price: number;
  currency: string;
  source: Source;
  booking_url?: string | null;
}

export interface Destination {
  origin: string;
  destination: string;
  city?: string | null;
  country?: string | null;
  price: number;
  currency: string;
  departure?: string | null;
  return_date?: string | null;
  source: Source;
  booking_url?: string | null;
  lat?: number | null;
  lon?: number | null;
}

export interface SearchQuery {
  origins: string[];
  destinations: string[];
  departure: string;
  return_date?: string | null;
  adults?: number;
  cabin?: Cabin;
  max_stops?: number | null;
  currency?: string;
  sources?: Source[];
  departure_flex_days?: number;
  return_flex_days?: number;
  nearby_km?: number;
}

export interface SearchResult {
  query: SearchQuery;
  trips: Trip[];
  errors: Record<string, string>;
  searched_at: string;
  google_url?: string | null;
}

export interface PlanRequest {
  origins: string[];
  destinations: string[];
  depart_start: string;
  depart_end: string;
  return_start?: string | null;
  return_end?: string | null;
  currency: string;
  max_stopover_days?: number;
  min_connection_hours?: number;
  max_trip_days?: number | null;
  hubs?: string[];
  max_hubs?: number;
  allow_self_transfer?: boolean;
  include_nested_roundtrips?: boolean;
  cabin?: Cabin;
  adults?: number;
}

export interface PlanResult {
  trips: Trip[];
  direct?: Trip | null;
  hubs_tried: string[];
  requests: number;
  errors: Record<string, string>;
}

export interface ExploreRequest {
  origin: string;
  start: string;
  end: string;
  currency: string;
  nights_min?: number | null;
  nights_max?: number | null;
  sources?: Source[];
}

export const CURRENCIES = ["NOK", "EUR", "USD", "GBP", "MXN"] as const;
export type Currency = (typeof CURRENCIES)[number];
