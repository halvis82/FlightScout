// Pinged by open FlightScout tabs on a local copy, so the on demand local
// site (flightscout local) knows it's still in use. No database, no work.
export const GET = () => new Response(null, { status: 204, headers: { "Cache-Control": "no-store" } });
