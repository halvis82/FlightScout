CREATE TABLE "fare_memory" (
	"origin" text NOT NULL,
	"dest" text NOT NULL,
	"day" date NOT NULL,
	"usd" double precision NOT NULL,
	"seen_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "fare_memory_origin_dest_day_pk" PRIMARY KEY("origin","dest","day")
);
--> statement-breakpoint
CREATE INDEX "fare_memory_dest" ON "fare_memory" USING btree ("dest","day");