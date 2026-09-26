import { intParam, json, requireUser, route } from "@/lib/api";
import { checkWatch } from "@/lib/watch-check";
import { ownWatch } from "@/lib/watches";
import { enforceRateLimit } from "@/lib/ratelimit";

export const maxDuration = 300;
type Ctx = { params: Promise<{ id: string }> };

export const POST = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const w = await ownWatch(userId, intParam((await params).id));
  await enforceRateLimit(req, "check", userId);
  return json(await checkWatch(w, userId));
});
