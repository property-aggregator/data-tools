import csv
import io
from importlib.resources import files


def read_county_codes() -> list[str]:
	"""Returns all county codes from the TERC register; the service's own county layer has geometry only."""
	resources = files("rcn.resources")
	terc = next(entry for entry in resources.iterdir() if entry.name.startswith("TERC_Urzedowy_"))

	with io.TextIOWrapper(terc.open("rb"), encoding="utf-8-sig") as source:
		rows = csv.DictReader(source, delimiter=";")
		codes = {row["WOJ"] + row["POW"] for row in rows if row["POW"] and not row["GMI"]}

	return sorted(codes)
