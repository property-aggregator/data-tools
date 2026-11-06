import gzip
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql

from rcn.layers import LAYERS

TABLE = "rcnTransactions"
NEXT_TABLE = "rcnTransactionsNext"
STAGING_COLUMNS = (
	"transactionId", "countyCode", "transactionDate", "marketType", "transactionPrice", "propertyRight", "share",
	"propertyPrice", "landArea", "objectId", "category", "zoning", "area", "price", "rooms", "floor", "address", "x", "y",
)
KINDS = {"units": "unit", "buildings": "building", "parcels": "parcel"}

# Counties report parcel areas (DZI_POW_EWID) and land areas (NIER_POW_GRUNTU) either in hectares or in square
# metres. The county median tells which: no county has typical plots under 5 m² or over 5 ha.
BUILD_SQL = f"""
CREATE TABLE "{NEXT_TABLE}" AS
WITH land_factor AS (
	SELECT "countyCode",
		CASE WHEN percentile_cont(0.5) WITHIN GROUP (ORDER BY "landArea"::float8) < 5 THEN 10000 ELSE 1 END AS "factor"
	FROM rcn_staging
	WHERE "landArea" IS NOT NULL
	GROUP BY "countyCode"
),
parcel_factor AS (
	SELECT "countyCode",
		CASE WHEN percentile_cont(0.5) WITHIN GROUP (ORDER BY "area"::float8) < 5 THEN 10000 ELSE 1 END AS "factor"
	FROM rcn_staging
	WHERE "kind" = 'parcel' AND "area" IS NOT NULL
	GROUP BY "countyCode"
)
SELECT DISTINCT ON (s."kind", s."transactionId", s."objectId")
	s."kind"::varchar(20) AS "kind",
	s."transactionId"::varchar(64) AS "transactionId",
	s."objectId" AS "objectId",
	s."countyCode"::varchar(4) AS "countyCode",
	s."transactionDate"::date AS "transactionDate",
	(CASE s."marketType" WHEN 'rynekPierwotny' THEN 'primary' WHEN 'rynekWtorny' THEN 'secondary' END)::varchar(20)
		AS "marketType",
	s."transactionPrice"::numeric AS "transactionPrice",
	s."propertyPrice"::numeric AS "propertyPrice",
	s."price"::numeric AS "price",
	round(s."area"::numeric * CASE WHEN s."kind" = 'parcel' THEN coalesce(p."factor", 1) ELSE 1 END, 2) AS "areaM2",
	round(s."landArea"::numeric * coalesce(l."factor", 1), 2) AS "landAreaM2",
	s."propertyRight" AS "propertyRight",
	s."share" AS "share",
	s."category" AS "category",
	s."zoning" AS "zoning",
	s."rooms"::numeric::int AS "rooms",
	s."floor"::numeric::int AS "floor",
	s."address" AS "address",
	ST_Transform(ST_SetSRID(ST_MakePoint(s."x"::float8, s."y"::float8), 2180), 4326)::geography(Point, 4326)
		AS "location"
FROM rcn_staging AS s
LEFT JOIN land_factor AS l ON l."countyCode" = s."countyCode"
LEFT JOIN parcel_factor AS p ON p."countyCode" = s."countyCode"
WHERE s."transactionId" IS NOT NULL
	AND s."objectId" IS NOT NULL
	AND s."transactionDate" IS NOT NULL
	AND s."x" IS NOT NULL
	AND s."y" IS NOT NULL
ORDER BY s."kind", s."transactionId", s."objectId"
"""

SWAP_SQL = (
	f'DROP TABLE IF EXISTS "{TABLE}"',
	f'ALTER TABLE "{NEXT_TABLE}" RENAME TO "{TABLE}"',
	f'ALTER TABLE "{TABLE}" ADD CONSTRAINT "pk_{TABLE}" PRIMARY KEY ("kind", "transactionId", "objectId")',
	f'CREATE INDEX "ix_{TABLE}_location" ON "{TABLE}" USING gist ("location")',
	f'CREATE INDEX "ix_{TABLE}_kind_transactionDate" ON "{TABLE}" ("kind", "transactionDate")',
	f'ANALYZE "{TABLE}"',
)


def import_files(input_directory: Path, conninfo: str) -> None:
	files = [(layer, input_directory / f"rcn-{layer.name}.tsv.gz") for layer in LAYERS]

	if missing := [str(path) for _, path in files if not path.exists()]:
		raise FileNotFoundError(f"Missing export files: {', '.join(missing)}")

	# One transaction: if anything fails, the previous data stays in place.
	with psycopg.connect(conninfo) as connection, connection.cursor() as cursor:
		columns = sql.SQL(", ").join(sql.SQL('{} text').format(sql.Identifier(column)) for column in STAGING_COLUMNS)
		cursor.execute(sql.SQL("CREATE TEMP TABLE rcn_staging (kind text, {}) ON COMMIT DROP").format(columns))

		for layer, path in files:
			_copy(cursor, path)
			cursor.execute("UPDATE rcn_staging SET kind = %s WHERE kind IS NULL", (KINDS[layer.name],))
			print(f"{layer.name}: {cursor.rowcount} rows loaded from {path.name}", flush=True)

		cursor.execute(f'DROP TABLE IF EXISTS "{NEXT_TABLE}"')
		cursor.execute(BUILD_SQL)
		print(f"{cursor.rowcount} transactions prepared, replacing \"{TABLE}\"", flush=True)

		for statement in SWAP_SQL:
			cursor.execute(statement)

		imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
		cursor.execute(
			sql.SQL("COMMENT ON TABLE {} IS {}").format(
				sql.Identifier(TABLE), sql.Literal(f"RCN transactions imported at {imported_at}")
			)
		)

	print(f"Imported into \"{TABLE}\"")


def _copy(cursor: psycopg.Cursor, path: Path) -> None:
	with gzip.open(path, "rt", encoding="utf-8", newline="") as source:
		header = source.readline().rstrip("\n").split("\t")

		if unknown := set(header) - set(STAGING_COLUMNS):
			raise ValueError(f"{path.name} has unknown columns: {', '.join(sorted(unknown))}")

		# CSV mode with a quote character that never occurs, so values are taken literally and empty means NULL.
		statement = sql.SQL("COPY rcn_staging ({}) FROM STDIN (FORMAT csv, DELIMITER E'\\t', QUOTE E'\\x01')").format(
			sql.SQL(", ").join(map(sql.Identifier, header))
		)

		with cursor.copy(statement) as copy:
			while chunk := source.read(1 << 20):
				copy.write(chunk)
