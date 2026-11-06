import gzip
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from rcn import wfs
from rcn.counties import read_county_codes
from rcn.layers import BUILDINGS, LAYERS, PARCELS, UNITS, Layer

MAX_PARALLEL_REQUESTS = 4


def export(since: date, output: Path, counties: list[str] | None = None) -> None:
	all_counties = read_county_codes()
	selected = sorted(counties) if counties else all_counties

	if unknown := set(selected) - set(all_counties):
		raise ValueError(f"Unknown county codes: {', '.join(sorted(unknown))}")

	parts_root = output / ".parts"
	parts_directory = parts_root / since.isoformat()

	# Parts left by an interrupted export with another window would mix stale rows into the files.
	if parts_root.exists():
		for stale in parts_root.iterdir():
			if stale != parts_directory:
				shutil.rmtree(stale)

	print(f"Exporting RCN transactions since {since.isoformat()} for {len(selected)} counties to {output.resolve()}")

	tasks = [(layer, county) for layer in LAYERS for county in selected]

	# Each county lands in its own part file, so an interrupted export resumes from the counties still missing.
	with ThreadPoolExecutor(MAX_PARALLEL_REQUESTS) as pool:
		futures = [pool.submit(_export_part, layer, county, since, parts_directory) for layer, county in tasks]

		for finished, future in enumerate(as_completed(futures), start=1):
			layer, county, rows = future.result()

			if rows is not None:
				print(f"[{finished}/{len(tasks)}] {layer.name} {county}: {rows}", flush=True)

	_merge(selected, parts_directory, output)
	shutil.rmtree(parts_root)


def _export_part(layer: Layer, county: str, since: date, parts_directory: Path) -> tuple[Layer, str, int | None]:
	path = _part_path(parts_directory, layer, county)

	if path.exists():
		return layer, county, None

	path.parent.mkdir(parents=True, exist_ok=True)
	temporary = path.with_suffix(".tmp")
	rows = 0

	with temporary.open("w", encoding="utf-8", newline="\n") as target:
		for row in wfs.read_county(layer, county, since):
			target.write("\t".join(_sanitize(row[header]) for header in layer.headers) + "\n")
			rows += 1

	temporary.replace(path)

	return layer, county, rows


def _merge(counties: list[str], parts_directory: Path, output: Path) -> None:
	# A parcel sold together with a unit or a building is only the land under it: its price is the price of the unit
	# or the house, which the other files already hold.
	transaction_index = PARCELS.headers.index("transactionId")
	property_right_index = PARCELS.headers.index("propertyRight")
	transactions_with_objects = {
		line.split("\t", 1)[0]
		for layer in (UNITS, BUILDINGS)
		for county in counties
		for line in _part_path(parts_directory, layer, county).open(encoding="utf-8")
	}

	def is_land_under_sold_object(fields: list[str]) -> bool:
		return (
			fields[transaction_index] in transactions_with_objects
			or fields[property_right_index].startswith("wlasnoscLokalu")
		)

	for layer in LAYERS:
		target = output / f"rcn-{layer.name}.tsv.gz"
		temporary = target.with_suffix(".tmp")
		rows = skipped = 0

		with gzip.open(temporary, "wt", encoding="utf-8", newline="\n", compresslevel=9) as writer:
			writer.write("\t".join(layer.headers) + "\n")

			for county in counties:
				for line in _part_path(parts_directory, layer, county).open(encoding="utf-8"):
					if layer is PARCELS and is_land_under_sold_object(line.rstrip("\n").split("\t")):
						skipped += 1
						continue

					writer.write(line)
					rows += 1

		temporary.replace(target)
		print(f"{layer.name}: {rows} rows ({skipped} skipped), {target.stat().st_size / 1024 / 1024:.1f} MB")


def _part_path(parts_directory: Path, layer: Layer, county: str) -> Path:
	return parts_directory / layer.name / f"{county}.tsv"


def _sanitize(value: str) -> str:
	return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
