# RCN – transaction prices

Exports transaction prices from the public Real Estate Price Register (RCN, *Rejestr Cen
Nieruchomości*), published by GUGiK as a WFS service at `https://mapy.geoportal.gov.pl/wss/service/rcn`,
and imports them into the `rcnTransactions` table of the backend database.

Counties upload their data in batches, months after the notarial deed, so the data only needs
refreshing from time to time (e.g. once a quarter): run `export`, commit the new files in `data/`,
then run `import`. The committed files let anyone import the data right after cloning, without the
1–2 hour export.

## Installation

Run all commands from this directory (`rcn/`).

```powershell
py -3 -m venv .venv
.\.venv\Scripts\activate          # Windows
# . .venv/bin/activate            # Linux/macOS
python -m pip install --upgrade pip
python -m pip install -e .
```

## Export

Downloads free-market sales (`wolnyRynek`) from the given date onwards for all 380 counties into
`./data`. A full export takes about 1–2 hours.

```bash
python -m rcn export [--since YYYY-MM-DD] [--output DIR] [--counties CODE ...]
```

| Option | Default | Description |
|---|---|---|
| `--since` | today minus 24 months | Earliest notarial deed date |
| `--output` | `data` | Where the files are written |
| `--counties` | all | Only these 4-digit TERYT county codes, e.g. `1465` (Warsaw) |

Examples:

```bash
# Last 24 months, all of Poland
python -m rcn export

# Fixed start date, e.g. to resume an interrupted export on another day
python -m rcn export --since 2024-11-05

# A quick look at a few counties without touching ./data
python -m rcn export --counties 1465 1261 --output test-data
```

Without `--since`, the start date moves every day, so an export interrupted and restarted on another
day starts from scratch; pass the date explicitly to resume it.

### Output files

| File | RCN layer | Records |
|---|---|---|
| `rcn-units.tsv.gz` | `lokale` | Residential units (`LOK_FUNKCJA = mieszkalna`) |
| `rcn-buildings.tsv.gz` | `budynki` | Residential buildings (`BUD_RODZAJ = mieszkalny`) |
| `rcn-parcels.tsv.gz` | `dzialki` | Parcels sold on their own, without roads and forests |

Gzip-compressed, tab-separated UTF-8 with a header row and `\n` line endings. Empty values are
empty strings. The full export of November 2026 (24 months) has about 415 000 units (23 MB),
966 000 buildings (37 MB) and 592 000 parcels (25 MB).

Every file has the transaction columns (`transactionId`, `countyCode`, `transactionDate`, `marketType`,
`transactionPrice`, `propertyRight`, `share`, `propertyPrice`, `landArea`), the object columns of its layer
(`objectId`, `area`, `price`, `address`, and `rooms` / `floor`, `category` or `zoning`) and the point
`x` / `y` in EPSG:2180 (easting / northing). Values are exported as RCN has them; units and cleanup
are handled by the import.

### How the export works

1. The county list comes from a copy of the TERC register in `src/rcn/resources`; the service's own
   county layer has geometry only, without codes. Replace the file when GUS publishes a new one.
2. For every layer and county, the export pages through the WFS service 1000 records at a time by
   offset, ordered by `gid`, 4 requests in parallel; failed or stalled requests are retried with a
   growing delay. The service sorts `gid` as text but filters it as a number, so paging by "`gid`
   greater than the last one" would repeat records. Rows repeated within a county are dropped.
3. Units are points in RCN; buildings and parcels are polygons, so their point is the centre of the
   polygon's bounding box.
4. Each county is saved to its own part file in `data/.parts/<since>/`, so an interrupted export
   resumes from the counties still missing. Parts of an export with a different start date are
   deleted first, so stale rows never mix into new files.
5. The parts are merged in county order into the three files, which replace the previous ones.
   Parcels sold together with a unit or a building (the same transaction is in the units or buildings
   file, or the right is `wlasnoscLokalu…`) are skipped: they are only the land under the apartment
   or the house, and their price is the price of the whole property.

## Import

Replaces the `rcnTransactions` table with the files from `./data`. The backend database has to
exist with its migrations applied (they enable PostGIS).

```bash
python -m rcn import [--input DIR] [--connection CONNECTION_STRING]
```

The connection string is read from `ConnectionStrings__DefaultConnection`, the same variable and
format the backend uses, so its value can be copied as is. A libpq string (`host=... dbname=...`)
or a `postgresql://` URL works too.

### Local database

The local database from the backend's `docker-compose.yml` (start it with `docker compose up -d` in
the backend repository):

PowerShell:

```powershell
$env:ConnectionStrings__DefaultConnection = "Host=localhost;Port=5432;Database=property_aggregator;Username=postgres;Password=postgres"
python -m rcn import
```

Bash:

```bash
export ConnectionStrings__DefaultConnection="Host=localhost;Port=5432;Database=property_aggregator;Username=postgres;Password=postgres"
python -m rcn import
```

Or in one command, without setting the variable:

```bash
python -m rcn import --connection "Host=localhost;Port=5432;Database=property_aggregator;Username=postgres;Password=postgres"
```

### Other databases

Use the connection string of the target environment. If its database is not reachable from your
machine, open a tunnel to it first (e.g. SSH port forwarding) and point `Host` / `Port` at the local
end of the tunnel. Add `SSL Mode=Require` when the server requires TLS.

### What the import does

Everything runs in one transaction; if any step fails, the previous data stays in place.

1. The three files are copied into a temporary table.
2. Counties report parcel and land areas either in hectares or in square metres; the county median
   tells which, and the values are converted to square metres.
3. Points are transformed from EPSG:2180 to WGS 84; rows repeated across counties are kept once.
4. The new data replaces `rcnTransactions`, and the indexes are built. Queries on the table wait
   only for this last step.

A full import takes a few minutes.

### Table

The table belongs to this tool, not to the backend's migrations: the import drops and recreates it.

| Column | Type | Description |
|---|---|---|
| `kind` | `varchar(20)` | `unit`, `building` or `parcel` |
| `transactionId` | `varchar(64)` | RCN transaction id; one transaction can cover several objects |
| `objectId` | `text` | Unit, building or parcel id |
| `countyCode` | `varchar(4)` | TERYT county code |
| `transactionDate` | `date` | Date of the notarial deed |
| `marketType` | `varchar(20)` | `primary`, `secondary` or null, as the backend's `MarketType` |
| `transactionPrice` | `numeric` | Gross price of the whole transaction |
| `propertyPrice` | `numeric` | Gross price of the property |
| `price` | `numeric` | Gross price of the object itself, often empty |
| `areaM2` | `numeric` | Usable area of a unit or building, area of a parcel, in m² |
| `landAreaM2` | `numeric` | Land area of the property, in m² |
| `propertyRight` | `text` | Right sold, e.g. `wlasnoscLokaluWrazZPrawemZwiazanym` |
| `share` | `text` | Share sold, e.g. `1/1` |
| `category` | `text` | Building kind or parcel land use |
| `zoning` | `text` | Parcel purpose in the local zoning plan |
| `rooms` | `int` | Number of rooms of a unit |
| `floor` | `int` | Floor of a unit |
| `address` | `text` | Address as RCN has it, e.g. `MSC:Warszawa;UL:ulica Hery;NR_PORZ:11` |
| `location` | `geography(Point, 4326)` | Point of the object |

Primary key: (`kind`, `transactionId`, `objectId`). Indexes: GiST on `location`, (`kind`, `transactionDate`).
