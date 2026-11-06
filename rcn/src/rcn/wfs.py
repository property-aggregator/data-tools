import sys
import threading
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator
from datetime import date

import requests

from rcn.layers import Layer, equal

SERVICE_URL = "https://mapy.geoportal.gov.pl/wss/service/rcn"
PAGE_SIZE = 1000
MAX_ATTEMPTS = 6

# The read timeout applies between received bytes, so it also ends a response that stalls halfway.
TIMEOUT = (30, 120)

MS = "{http://mapserver.gis.umn.edu/mapserver}"
GML = "{http://www.opengis.net/gml/3.2}"

_sessions = threading.local()


def read_county(layer: Layer, county: str, since: date) -> Iterator[dict[str, str]]:
	"""Yields the county's records once each.

	The service sorts gid as text but filters it as a number, so keyset paging by gid repeats records whenever
	a county mixes gids of different lengths. The text order is still stable, so offsets are used instead.
	"""
	seen: set[tuple[str, str]] = set()
	start_index = 0

	while True:
		page = _get_page(layer, county, since, start_index)
		features = list(page.iter(MS + layer.type_name))

		if not features:
			return

		for feature in features:
			row = _read_feature(feature, layer)
			key = (row["transactionId"], row["objectId"])

			if key not in seen:
				seen.add(key)
				yield row

		start_index += PAGE_SIZE


def _read_feature(feature: ElementTree.Element, layer: Layer) -> dict[str, str]:
	row = {}

	for header, field in layer.columns:
		element = feature.find(MS + field)
		row[header] = "".join(element.itertext()).strip() if element is not None else ""

	# Units are points and buildings and parcels are polygons; the centre of the envelope covers both.
	# EPSG:2180 lists northing before easting.
	lower = _parse_corner(feature.findtext(f"{GML}boundedBy/{GML}Envelope/{GML}lowerCorner"))
	upper = _parse_corner(feature.findtext(f"{GML}boundedBy/{GML}Envelope/{GML}upperCorner"))

	if lower and upper:
		row["x"] = f"{(lower[1] + upper[1]) / 2:.2f}"
		row["y"] = f"{(lower[0] + upper[0]) / 2:.2f}"
	else:
		row["x"] = row["y"] = ""

	return row


def _parse_corner(value: str | None) -> tuple[float, float] | None:
	parts = (value or "").split()

	return (float(parts[0]), float(parts[1])) if len(parts) == 2 else None


def _get_page(layer: Layer, county: str, since: date, start_index: int) -> ElementTree.Element:
	filter_xml = (
		'<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0" xmlns:ms="http://mapserver.gis.umn.edu/mapserver">'
		"<fes:And>"
		+ equal("TERYT", county)
		+ equal("TRAN_RODZAJ_TRANS", "wolnyRynek")
		+ "<fes:PropertyIsGreaterThanOrEqualTo><fes:ValueReference>ms:DOK_DATA</fes:ValueReference>"
		+ f"<fes:Literal>{since.isoformat()}</fes:Literal></fes:PropertyIsGreaterThanOrEqualTo>"
		+ layer.extra_filter
		+ "</fes:And></fes:Filter>"
	)
	params = {
		"SERVICE": "WFS",
		"VERSION": "2.0.0",
		"REQUEST": "GetFeature",
		"TYPENAMES": f"ms:{layer.type_name}",
		"COUNT": PAGE_SIZE,
		"STARTINDEX": start_index,
		"SORTBY": "gid ASC",
		"PROPERTYNAME": ",".join([field for _, field in layer.columns] + ["gid", "GEOMETRIA"]),
		"FILTER": filter_xml,
	}

	for attempt in range(1, MAX_ATTEMPTS + 1):
		try:
			response = _session().get(SERVICE_URL, params=params, timeout=TIMEOUT)
			response.raise_for_status()
			root = ElementTree.fromstring(response.content)

			if root.tag.endswith("ExceptionReport"):
				raise RuntimeError(f"WFS error for {layer.type_name} {county}: {''.join(root.itertext()).strip()}")

			return root
		except (requests.RequestException, ElementTree.ParseError, RuntimeError) as error:
			if attempt == MAX_ATTEMPTS:
				raise

			print(f"Retrying {layer.type_name} {county} at {start_index}: {error}", file=sys.stderr)
			time.sleep(2**attempt)

	raise AssertionError("unreachable")


def _session() -> requests.Session:
	if not hasattr(_sessions, "session"):
		_sessions.session = requests.Session()

	return _sessions.session
