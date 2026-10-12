"""Execute a supplied SQL file against the read-only analytical database and print the result."""

# Use Path to build file locations reliably on Windows.
from pathlib import Path
# Read the SQL filename passed on the command line.
import sys
# Use DuckDB to query CSV files and the analytical database.
import duckdb

# Locate the project folder relative to this script.
ROOT = Path(__file__).resolve().parents[1]
# Set the DuckDB database path.
DB_PATH = ROOT / "analysis.duckdb"

# Require exactly one SQL filename; otherwise show the usage instructions.
if len(sys.argv) != 2:
    # Stop with an explanatory error when the required input is unavailable.
    raise SystemExit(
        "Usage: python src/run_sql.py sql/file.sql"
    )

# Resolve the SQL file supplied on the command line.
sql_file = ROOT / sys.argv[1]

# Read the SQL statements from the file.
sql = sql_file.read_text(encoding="utf-8")

# Open the database connection.
con = duckdb.connect(str(DB_PATH), read_only=True)

result = con.execute(sql)
# Show progress or results in the terminal.
print(result.df().to_string(index=False))

# Close the database connection.
con.close()
