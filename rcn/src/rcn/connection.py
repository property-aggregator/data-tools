from psycopg.conninfo import make_conninfo

# Npgsql keywords, so the backend's ConnectionStrings__DefaultConnection value can be used as is.
NPGSQL_KEYWORDS = {
	"host": "host",
	"server": "host",
	"port": "port",
	"database": "dbname",
	"username": "user",
	"user id": "user",
	"user": "user",
	"password": "password",
	"ssl mode": "sslmode",
	"sslmode": "sslmode",
}


def to_conninfo(connection_string: str) -> str:
	"""Accepts an Npgsql string (Host=...;Port=...), a libpq string (host=... port=...) or a postgresql:// URL."""
	if ";" not in connection_string:
		return connection_string

	parameters = {}

	for pair in filter(str.strip, connection_string.split(";")):
		key, _, value = pair.partition("=")
		keyword = NPGSQL_KEYWORDS.get(key.strip().lower())

		if keyword is None:
			raise ValueError(f"Unsupported connection string keyword '{key.strip()}'")

		parameters[keyword] = value.strip().lower() if keyword == "sslmode" else value.strip()

	return make_conninfo(**parameters)
