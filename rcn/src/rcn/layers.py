from dataclasses import dataclass

COMMON_COLUMNS = (
	("transactionId", "TRAN_LOKALNY_ID_IIP"),
	("countyCode", "TERYT"),
	("transactionDate", "DOK_DATA"),
	("marketType", "TRAN_RODZAJ_RYNKU"),
	("transactionPrice", "TRAN_CENA_BRUTTO"),
	("propertyRight", "NIER_PRAWO"),
	("share", "NIER_UDZIAL"),
	("propertyPrice", "NIER_CENA_BRUTTO"),
	("landArea", "NIER_POW_GRUNTU"),
)


def equal(field: str, value: str) -> str:
	return (
		f"<fes:PropertyIsEqualTo><fes:ValueReference>ms:{field}</fes:ValueReference>"
		f"<fes:Literal>{value}</fes:Literal></fes:PropertyIsEqualTo>"
	)


def not_equal(field: str, value: str) -> str:
	return (
		f"<fes:PropertyIsNotEqualTo><fes:ValueReference>ms:{field}</fes:ValueReference>"
		f"<fes:Literal>{value}</fes:Literal></fes:PropertyIsNotEqualTo>"
	)


@dataclass(frozen=True)
class Layer:
	name: str
	type_name: str
	extra_filter: str
	columns: tuple[tuple[str, str], ...]

	@property
	def headers(self) -> list[str]:
		return [header for header, _ in self.columns] + ["x", "y"]


UNITS = Layer(
	"units",
	"lokale",
	equal("LOK_FUNKCJA", "mieszkalna"),
	COMMON_COLUMNS + (
		("objectId", "LOK_ID_LOKALU"),
		("area", "LOK_POW_UZYT"),
		("price", "LOK_CENA_BRUTTO"),
		("rooms", "LOK_LICZBA_IZB"),
		("floor", "LOK_NR_KOND"),
		("address", "LOK_ADRES"),
	),
)

BUILDINGS = Layer(
	"buildings",
	"budynki",
	equal("BUD_RODZAJ", "mieszkalny"),
	COMMON_COLUMNS + (
		("objectId", "BUD_ID_BUDYNKU"),
		("category", "BUD_RODZAJ"),
		("area", "BUD_POW_UZYT"),
		("price", "BUD_CENA_BRUTTO"),
		("address", "BUD_ADRES"),
	),
)

# Roads and forests say nothing about plot prices.
PARCELS = Layer(
	"parcels",
	"dzialki",
	not_equal("DZI_SPOSOB_UZYT", "terenyKomunikacyjne") + not_equal("DZI_SPOSOB_UZYT", "gruntyLesne"),
	COMMON_COLUMNS + (
		("objectId", "DZI_ID_DZIALKI"),
		("category", "DZI_SPOSOB_UZYT"),
		("zoning", "DZI_PRZEZN_WMPZP"),
		("area", "DZI_POW_EWID"),
		("price", "DZI_CENA_BRUTTO"),
		("address", "DZI_ADRES"),
	),
)

LAYERS = (UNITS, BUILDINGS, PARCELS)
