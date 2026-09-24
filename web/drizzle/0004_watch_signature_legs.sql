ALTER TABLE "places" ADD COLUMN "signature" text;--> statement-breakpoint
ALTER TABLE "watches" ADD COLUMN "legs" jsonb;--> statement-breakpoint
ALTER TABLE "watches" ADD COLUMN "signature" text;--> statement-breakpoint
-- Backfill signatures the same way src/lib/signature.ts computes them.
UPDATE "watches" SET "signature" = concat_ws('|',
  (SELECT string_agg(x, ',' ORDER BY x) FROM unnest("origins") x),
  (SELECT string_agg(x, ',' ORDER BY x) FROM unnest("destinations") x),
  "trip_type", "depart_start"::text, "depart_end"::text,
  coalesce("nights_min"::text, ''), coalesce("nights_max"::text, ''), "cabin", "adults"::text, '');--> statement-breakpoint
UPDATE "places" SET "signature" = (SELECT string_agg(x, ',' ORDER BY x) FROM unnest("codes") x);--> statement-breakpoint
-- Remove existing duplicates (keep the oldest) so the unique indexes can be created.
DELETE FROM "observations" WHERE "watch_id" IN (
  SELECT id FROM "watches" w WHERE EXISTS (
    SELECT 1 FROM "watches" o WHERE o.user_id = w.user_id AND o.signature = w.signature AND o.id < w.id));--> statement-breakpoint
DELETE FROM "watches" w WHERE EXISTS (
  SELECT 1 FROM "watches" o WHERE o.user_id = w.user_id AND o.signature = w.signature AND o.id < w.id);--> statement-breakpoint
DELETE FROM "places" p WHERE EXISTS (
  SELECT 1 FROM "places" o WHERE o.user_id = p.user_id AND o.signature = p.signature AND o.id < p.id);--> statement-breakpoint
CREATE UNIQUE INDEX "places_user_sig_idx" ON "places" USING btree ("user_id","signature");--> statement-breakpoint
CREATE UNIQUE INDEX "watches_user_sig_idx" ON "watches" USING btree ("user_id","signature");
