-- The documents an analysis read, so an approval can be bound to them. NULL for analyses made before this migration.
ALTER TABLE analyses ADD COLUMN evidence_hash text;
