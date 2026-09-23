CREATE TABLE "explore_cache" (
	"origin" text PRIMARY KEY NOT NULL,
	"currency" text NOT NULL,
	"items" jsonb NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
