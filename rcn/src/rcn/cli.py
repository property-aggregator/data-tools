import argparse
import os
import sys
from datetime import date
from pathlib import Path

from rcn.connection import to_conninfo
from rcn.export import export
from rcn.importer import import_files

CONNECTION_STRING_VARIABLE = "ConnectionStrings__DefaultConnection"


def main(argv: list[str] | None = None) -> None:
	parser = argparse.ArgumentParser(prog="rcn", description="Exports RCN transaction prices and imports them into PostgreSQL.")
	commands = parser.add_subparsers(dest="command", required=True)

	export_parser = commands.add_parser("export", help="download transactions from the RCN WFS service into files")
	export_parser.add_argument("--since", type=date.fromisoformat, help="earliest notarial deed date, default 24 months ago")
	export_parser.add_argument("--output", type=Path, default=Path("data"), help="output directory, default ./data")
	export_parser.add_argument("--counties", nargs="+", metavar="CODE", help="only these 4-digit county codes")

	import_parser = commands.add_parser("import", help="replace the rcnTransactions table with the exported files")
	import_parser.add_argument("--input", type=Path, default=Path("data"), help="directory with the files, default ./data")
	import_parser.add_argument("--connection", help=f"connection string, default ${CONNECTION_STRING_VARIABLE}")

	args = parser.parse_args(argv)

	if args.command == "export":
		export(args.since or _years_ago(date.today(), 2), args.output, args.counties)
	else:
		connection_string = args.connection or os.environ.get(CONNECTION_STRING_VARIABLE)

		if not connection_string:
			sys.exit(f"Pass --connection or set {CONNECTION_STRING_VARIABLE}")

		import_files(args.input, to_conninfo(connection_string))


def _years_ago(today: date, years: int) -> date:
	try:
		return today.replace(year=today.year - years)
	except ValueError:
		return today.replace(year=today.year - years, day=28)
