-- Defaults set by the old onboarding merged every home (e.g. OSL, TRF, SAN)
-- into one origin. Clear them so searches start from the last used origin.
UPDATE "settings" SET "default_origins" = '{}' WHERE cardinality("default_origins") > 1;
