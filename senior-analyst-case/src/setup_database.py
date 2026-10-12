"""Load raw CSV files into analysis.duckdb; existing tables with matching names are replaced."""

# Use Path to build file locations reliably on Windows.
from pathlib import Path
# Use regular expressions to make safe table names from filenames.
import re
# Use DuckDB to query CSV files and the analytical database.
import duckdb

# Locate the project folder relative to this script.
ROOT = Path(__file__).resolve().parents[1]
# Set the folder containing source CSV files.
RAW_DIR = ROOT / "data" / "raw"
# Choose the folder for temporary database files.
TEMP_DIR = ROOT / "duckdb_tmp"
# Set the DuckDB database path.
DB_PATH = ROOT / "analysis.duckdb"

# Create the output folder if it does not exist.
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Open the database connection.
con = duckdb.connect(str(DB_PATH))

# Limit database memory use; larger operations can spill to the temporary folder.
con.execute("SET memory_limit = '16GB'")
# Allow DuckDB to use four worker threads.
con.execute("SET threads = 4")

# Tell DuckDB where to store temporary files.
con.execute(
    "SET temp_directory = ?",
    [str(TEMP_DIR)]
)

# Find and sort source CSV files.
csv_files = sorted(RAW_DIR.glob("*.csv"))

# Stop if there are no input CSV files to load.
if not csv_files:
    # Stop with an explanatory error when the required input is unavailable.
    raise FileNotFoundError(
        f"No CSV files found in {RAW_DIR}"
    )

for file in csv_files:
    # Create safe SQL table names
    table_name = re.sub(
        r"[^a-zA-Z0-9_]",
        "_",
        file.stem.lower()
    )

    # Prefix table names that start with a number so they are valid identifiers.
    if table_name[0].isdigit():
        # Convert the CSV filename into a safe SQL table name.
        table_name = "data_" + table_name

    # Show progress or results in the terminal.
    print(f"Loading {file.name}...")

    # Load this CSV into a database table, replacing any previous table with this name.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE "{table_name}" AS
        SELECT *
        FROM read_csv_auto(?)
        """,
        [str(file)]
    )

    # Count rows in the newly loaded table.
    row_count = con.execute(
        f'SELECT COUNT(*) FROM "{table_name}"'
    ).fetchone()[0]

    # Show progress or results in the terminal.
    print(
        f"Created {table_name}: "
        f"{row_count:,} rows"
    )

# Close the database connection.
con.close()
# Show progress or results in the terminal.
print("Database setup complete.")
