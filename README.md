# Property Aggregator – Data tools

Scripts that fetch external datasets and load them into the Property Aggregator database.
They are run by hand when a dataset changes, not by the backend.

| Tool | Dataset | Description |
|---|---|---|
| [`rcn`](rcn/README.md) | Real Estate Price Register (RCN) | Exports transaction prices of apartments, residential buildings and parcels from the GUGiK WFS service and imports them into PostgreSQL |

Each tool lives in its own directory with its own `pyproject.toml` and README.

## Requirements

- Python 3.11+
- Access to the PostgreSQL database of the [backend](https://github.com/property-aggregator/backend)
  (with its migrations applied) for tools that import data
