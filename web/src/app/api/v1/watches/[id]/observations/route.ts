import { body, intParam, json, requireUser, route, HttpError } from "@/lib/api";
import { recordObservations, type ObservationInput } from "@/lib/observations";
import { ownWatch } from "@/lib/watches";

type Ctx = { params: Promise<{ id: string }> };

export const POST = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const w = await ownWatch(userId, intParam((await params).id));
  const obs = await body<ObservationInput[] | { observations: ObservationInput[] }>(req);
  const list = Array.isArray(obs) ? obs : obs.observations;
  if (!Array.isArray(list)) throw new HttpError(400, "expected an array of observations");
  return json(await recordObservations(w, list), 201);
});
