CREATE INDEX "search_cache_time_idx" ON "search_cache" USING btree ("created_at");--> statement-breakpoint
CREATE INDEX "searches_kind_time_idx" ON "searches" USING btree ("kind","created_at");