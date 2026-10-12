"""Profile CSVs and a read-only DuckDB database using SQL, without pandas.

Run: .venv/Scripts/python.exe src/data_quality_report.py
Only aggregate results are fetched into Python. CSV data stays in DuckDB.
"""
# Use Path to build file locations reliably on Windows.
from pathlib import Path
# Allow database, input, and output paths to be supplied on the command line.
import argparse
# Write profiling results as CSV tables.
import csv
# Generate dataset pairs for join checks.
import itertools
# Export all profiling results in a single JSON report.
import json
# Use DuckDB to query CSV files and the analytical database.
import duckdb


# Locate the project folder relative to this script.
ROOT = Path(__file__).resolve().parents[1]


# Quote SQL identifiers safely.
def ident(value):
    return '"' + value.replace('"', '""') + '"'


# Quote SQL string values safely.
def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


# Run the full data quality profiling and export reports.
def main():
    # Create the command-line options parser.
    parser = argparse.ArgumentParser(description=__doc__)
    # Define an optional command-line setting.
    parser.add_argument('--database', type=Path, default=ROOT / 'analysis.duckdb')
    # Define an optional command-line setting.
    parser.add_argument('--raw-dir', type=Path, default=ROOT / 'data/raw')
    # Define an optional command-line setting.
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs/tables')
    # Read the command-line options.
    args = parser.parse_args()
    # Create the output folder if it does not exist.
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # Open the database connection.
    con = duckdb.connect(':memory:')
    # Limit database memory use; larger operations can spill to the temporary folder.
    con.execute("SET memory_limit = '2GB'")
    # Allow DuckDB to use four worker threads.
    con.execute('SET threads = 4')
    # Choose a writable folder for DuckDB to spill large operations to disk.
    temp = args.output_dir / '.duckdb_tmp'
    # Create the output folder if it does not exist.
    temp.mkdir(exist_ok=True)
    # Tell DuckDB where to store temporary files.
    con.execute(f'SET temp_directory = {literal(temp)}')
    # Attach the existing database read-only so profiling cannot modify it.
    con.execute(f'ATTACH {literal(args.database.resolve())} AS existing (READ_ONLY)')
    # Create containers for the data quality reports.
    reports = {name: [] for name in ['datasets', 'columns', 'date_ranges',
               'key_candidates', 'join_keys', 'source_comparison', 'business_checks',
               'monthly_coverage']}
    # Collect the datasets to profile.
    datasets = []

    # Execute SQL and return rows as dictionaries.
    def query(sql):
        result = con.execute(sql)
        # Extract column names so query results can be returned as dictionaries.
        names = [col[0] for col in result.description]
        return [dict(zip(names, row)) for row in result.fetchall()]

    # Discover all base tables in the attached read-only database.
    tables = query("SELECT table_schema, table_name FROM information_schema.tables "
                   "WHERE table_catalog = 'existing' AND table_type = 'BASE TABLE' "
                   "ORDER BY table_schema, table_name")
    for table in tables:
        name = table['table_name']
        # Add this result to the report collection.
        datasets.append(('database', name,
                         f'existing.{ident(table["table_schema"])}.{ident(name)}'))
    for index, path in enumerate(sorted(args.raw_dir.glob('*.csv'))):
        # Give each source CSV a separate temporary table name.
        view = f'raw_{index}'
        # Full-file inference, strict parsing: malformed rows are never skipped.
        con.execute(f'CREATE TEMP TABLE {ident(view)} AS SELECT * FROM '
                    f'read_csv_auto({literal(path.resolve())}, sample_size=-1, '
                    'header=true, ignore_errors=false)')
        # Add this result to the report collection.
        datasets.append(('csv', path.stem.lower(), ident(view)))
    # Stop if neither database tables nor CSV files were found.
    if not datasets:
        # Stop with an explanatory error when the required input is unavailable.
        raise RuntimeError('No tables or CSV files found')
    # Store column types for each dataset.
    schemas = {}
    # Store row counts for each dataset.
    counts = {}
    for source, name, relation in datasets:
        # Show progress or results in the terminal.
        print(f'Profiling {source}: {name}', flush=True)
        # Read the dataset column names and types.
        schema = [(r['column_name'], r['column_type'])
                  for r in query(f'DESCRIBE SELECT * FROM {relation}')]
        schemas[(source, name)] = schema
        row = query(f'SELECT count(*) AS row_count FROM {relation}')[0]
        count = row['row_count']
        counts[(source, name)] = count
        # Count repeated rows and their excess copies.
        duplicate = query(
            f'SELECT count(*) AS duplicate_groups, coalesce(sum(n-1),0) AS duplicate_excess_rows '
            f'FROM (SELECT {", ".join(ident(c) for c, _ in schema)}, count(*) AS n '
            f'FROM {relation} GROUP BY ALL HAVING count(*)>1)')[0]
        # Attach source and dataset labels to every profiling result.
        base = dict(source=source, dataset=name)
        # Add this result to the report collection.
        reports['datasets'].append(dict(base, row_count=count, column_count=len(schema), **duplicate))
        # Build one SQL query to measure nulls, blanks, and distinct values for all columns.
        expressions = []
        for i, (column, dtype) in enumerate(schema):
            col = ident(column)
            # Add these checks to the existing collection.
            expressions += [f'count(*) FILTER (WHERE {col} IS NULL) AS n{i}',
                            f'count(DISTINCT {col}) AS d{i}',
                            f"count(*) FILTER (WHERE trim({col}) = '') AS b{i}" if dtype == 'VARCHAR'
                            else f'0 AS b{i}']
        # Calculate missing-value and distinct-value statistics.
        stats = query(f'SELECT {", ".join(expressions)} FROM {relation}')[0]
        for i, (column, dtype) in enumerate(schema):
            # Retrieve this column's missing-value and distinct-value counts.
            nulls, blanks, distinct = stats[f'n{i}'], stats[f'b{i}'], stats[f'd{i}']
            # Add this result to the report collection.
            reports['columns'].append(dict(base, column=column, data_type=dtype,
                null_count=nulls, blank_count=blanks, missing_count=nulls+blanks,
                missing_pct=round(100*(nulls+blanks)/count, 4) if count else None,
                distinct_non_null=distinct))
            # Check date ranges and parsing for date-like columns.
            if dtype.startswith(('DATE', 'TIMESTAMP')) or column.endswith(('_ts', '_date', '_month')):
                # Try converting values to timestamps; invalid values become SQL NULL for counting.
                date_expr = f'TRY_CAST({ident(column)} AS TIMESTAMP)'
                # Calculate date ranges and count invalid dates.
                bounds = query(f'SELECT min({date_expr}) AS min_date, '
                               f'max({date_expr}) AS max_date, count(*) FILTER '
                               f'(WHERE {ident(column)} IS NOT NULL AND {date_expr} IS NULL) '
                               f'AS invalid_date_rows FROM {relation}')[0]
                # Add this result to the report collection.
                reports['date_ranges'].append(dict(base, column=column, **bounds))
            # Treat identifier columns as candidate unique keys.
            if column.endswith('_id'):
                # Add this result to the report collection.
                reports['key_candidates'].append(dict(base, key_columns=column,
                    null_key_rows=nulls, distinct_non_null_keys=distinct,
                    duplicate_excess_non_null=count-nulls-distinct,
                    is_unique_non_null=(nulls == 0 and count == distinct and count > 0)))
        # Choose the expected identifying columns for the dataset.
        grain = {'analytical_task_old_learning_minute_data': ['activity_month', 'lo_id'],
                 'analytical_task_new_learning_minute_data_daily': ['activity_date', 'enrolment_id', 'lo_id']}.get(name)
        # Check the expected composite key when all its columns are available.
        if grain and all(c in dict(schema) for c in grain):
            # Build the list of columns that should identify a unique activity record.
            keys = ', '.join(ident(c) for c in grain)
            # Flag records missing any part of the expected composite key.
            null_condition = ' OR '.join(f'{ident(c)} IS NULL' for c in grain)
            k = query(f'SELECT count(*) FILTER (WHERE {null_condition}) AS null_key_rows, '
                      f'count(DISTINCT ({keys})) FILTER (WHERE NOT ({null_condition})) '
                      f'AS distinct_non_null_keys FROM {relation}')[0]
            # Count non-null records beyond the number of distinct keys.
            excess = count-k['null_key_rows']-k['distinct_non_null_keys']
            # Add this result to the report collection.
            reports['key_candidates'].append(dict(base, key_columns=' + '.join(grain), **k,
                duplicate_excess_non_null=excess,
                is_unique_non_null=(k['null_key_rows']==0 and excess==0 and count>0)))
        for column, dtype in schema:
            # Validate learning-minute and course-duration numeric values.
            if column.startswith('learning_minutes_') or column == 'lo_duration_in_minutes':
                col = f'TRY_CAST({ident(column)} AS DOUBLE)'
                # Calculate numeric or metadata quality measures.
                metrics = query(f'SELECT min({col}) AS minimum, max({col}) AS maximum, '
                    f'count(*) FILTER (WHERE {col}<0) AS negative_rows, '
                    f'count(*) FILTER (WHERE {col}=0) AS zero_rows, '
                    f'count(*) FILTER (WHERE NOT isfinite({col})) AS non_finite_rows, '
                    f'count(*) FILTER (WHERE {col}>1440) AS above_1440_rows, '
                    f'count(*) FILTER (WHERE {ident(column)} IS NOT NULL AND {col} IS NULL) '
                    f'AS invalid_numeric_rows FROM {relation}')[0]
                for metric, value in metrics.items():
                    # Add this result to the report collection.
                    reports['business_checks'].append(dict(base, check=f'{column}.{metric}', value=value))
                # Choose the daily or monthly date column for activity coverage checks.
                date_column = 'activity_date' if 'activity_date' in dict(schema) else 'activity_month'
                # Calculate monthly coverage only when an activity date is available.
                if date_column in dict(schema):
                    # Summarise learning activity by month.
                    monthly = query(f"SELECT date_trunc('month', TRY_CAST({ident(date_column)} AS TIMESTAMP)) AS month, "
                        f'count(*) AS row_count, count(DISTINCT lo_id) AS distinct_learning_objects, '
                        f'sum({col}) AS learning_minutes FROM {relation} GROUP BY 1 ORDER BY 1')
                    # Add these results to the report collection.
                    reports['monthly_coverage'].extend(dict(base, **row) for row in monthly)
        # Check lifecycle dates when the creation timestamp is available.
        if 'lo_created_ts' in dict(schema):
            for label, condition in {
                'updated_before_created': 'TRY_CAST(lo_updated_ts AS TIMESTAMP) < TRY_CAST(lo_created_ts AS TIMESTAMP)',
                'decommissioned_before_created': 'TRY_CAST(lo_decommissioned_ts AS TIMESTAMP) < TRY_CAST(lo_created_ts AS TIMESTAMP)',
                'decommissioned_rows': 'lo_decommissioned_ts IS NOT NULL',
                'created_epoch_placeholder_rows': "TRY_CAST(lo_created_ts AS TIMESTAMP) = TIMESTAMP '1970-01-01'",
                'updated_epoch_placeholder_rows': "TRY_CAST(lo_updated_ts AS TIMESTAMP) = TIMESTAMP '1970-01-01'",
            }.items():
                value = query(f'SELECT count(*) AS n FROM {relation} WHERE {condition}')[0]['n']
                # Add this result to the report collection.
                reports['business_checks'].append(dict(base, check=label, value=value))

    # Check each dataset pair for shared identifiers and potential join inflation.
    for (source, name, relation), (other_source, other, right) in itertools.combinations(datasets, 2):
        # Skip cross-source joins; compare datasets within the same source.
        if source != other_source:
            # Skip this item because it does not meet the comparison conditions.
            continue
        # Find identifiers shared by the two datasets.
        common = set(dict(schemas[(source, name)])) & set(dict(schemas[(source, other)]))
        for key in sorted(c for c in common if c.endswith('_id')):
            # Check join coverage in both directions because missing matches may differ.
            for left_name, left, right_name, target in [(name, relation, other, right), (other, right, name, relation)]:
                col = ident(key)
                result = query(f'WITH target AS (SELECT {col} AS k, count(*) AS n FROM {target} '
                    f'WHERE {col} IS NOT NULL GROUP BY {col}) '
                    f'SELECT count(*) AS left_rows, count(*) FILTER (WHERE l.{col} IS NULL) AS null_left_keys, '
                    'count(*) FILTER (WHERE t.k IS NOT NULL) AS matched_left_rows, '
                    f'count(*) FILTER (WHERE l.{col} IS NOT NULL AND t.k IS NULL) AS unmatched_left_rows, '
                    'coalesce(sum(t.n),0) AS inner_join_rows, '
                    'count(*) FILTER (WHERE t.n>1) AS left_rows_with_multiple_matches '
                    f'FROM {left} l LEFT JOIN target t ON l.{col}=t.k')[0]
                # Add this result to the report collection.
                reports['join_keys'].append(dict(source=source, left_dataset=left_name,
                    right_dataset=right_name, key=key, **result))
    # Map database dataset names to their SQL table references.
    db = {name: relation for source, name, relation in datasets if source == 'database'}
    # Identify the table containing learning-object metadata.
    dimension_name = 'analytical_task_dim_learning_object'
    # Identify the table containing daily new-calculation learning minutes.
    daily_name = 'analytical_task_new_learning_minute_data_daily'
    for source in ('database', 'csv'):
        # Build table references for the current source: database or raw CSV.
        relations = {name: rel for s, name, rel in datasets if s == source}
        # Run activity-to-metadata checks only when both required tables exist.
        if dimension_name in relations and daily_name in relations:
            # Select activity and metadata tables for missing-metadata checks.
            activity, dimension = relations[daily_name], relations[dimension_name]
            # Calculate numeric or metadata quality measures.
            metrics = query('SELECT count(*) FILTER (WHERE d.lo_id IS NULL) AS missing_metadata_rows, '
                'coalesce(sum(n.learning_minutes_capped_new) FILTER (WHERE d.lo_id IS NULL),0) '
                'AS minutes_without_metadata, '
                'count(*) FILTER (WHERE d.lo_duration_in_minutes IS NULL) AS activity_rows_without_duration, '
                'count(*) FILTER (WHERE d.lo_topic_name IS NULL) AS activity_rows_without_topic, '
                'count(*) FILTER (WHERE d.lo_decommissioned_ts < n.activity_date) '
                'AS activity_rows_after_decommissioning '
                f'FROM {activity} n LEFT JOIN {dimension} d USING (lo_id)')[0]
            # Add these results to the report collection.
            reports['business_checks'].extend(dict(source=source, dataset=daily_name, check=k, value=v)
                                              for k, v in metrics.items())
    for source, name, relation in datasets:
        # Skip datasets without a matching CSV and database table.
        if source != 'csv' or name not in db:
            # Skip this item because it does not meet the comparison conditions.
            continue
        # Check whether CSV and database column types match.
        same_schema = schemas[('csv', name)] == schemas[('database', name)]
        result = dict(dataset=name, schema_matches=same_schema,
                      csv_rows=counts[('csv', name)], database_rows=counts[('database', name)])
        # Compare records directly when their column names and types match.
        if same_schema:
            # EXCEPT ALL compares exact multisets, including duplicate multiplicities.
            for label, left, right in [('csv_only_rows', relation, db[name]),
                                       ('database_only_rows', db[name], relation)]:
                # Count rows present in one source but absent from the other, including duplicates.
                result[label] = query(f'SELECT count(*) AS n FROM '
                                      f'(SELECT * FROM {left} EXCEPT ALL SELECT * FROM {right})')[0]['n']
            # Record the method used to compare the two sources.
            result['comparison_basis'] = 'exact typed multiset'
        # If column names match but types differ, compare after casting to database types.
        elif [c for c, _ in schemas[('csv', name)]] == [c for c, _ in schemas[('database', name)]]:
            # Build conversions to the database column types.
            casts = ', '.join(f'TRY_CAST({ident(c)} AS {dtype}) AS {ident(c)}'
                              for c, dtype in schemas[('database', name)])
            # Build a check for values that cannot be converted.
            invalid = ' OR '.join(f'({ident(c)} IS NOT NULL AND TRY_CAST({ident(c)} AS {dtype}) IS NULL)'
                                 for c, dtype in schemas[('database', name)])
            # Count CSV records containing values incompatible with the database schema.
            result['csv_rows_failing_database_cast'] = query(
                f'SELECT count(*) AS n FROM {relation} WHERE {invalid}')[0]['n']
            # Represent CSV records converted to the database column types.
            converted = f'(SELECT {casts} FROM {relation})'
            for label, left, right in [('csv_only_rows', converted, db[name]),
                                       ('database_only_rows', db[name], converted)]:
                # Count rows present in one source but absent from the other, including duplicates.
                result[label] = query(f'SELECT count(*) AS n FROM '
                                      f'(SELECT * FROM {left} EXCEPT ALL SELECT * FROM {right})')[0]['n']
            # Record the method used to compare the two sources.
            result['comparison_basis'] = 'multiset after casting CSV to database types; textual precision may change'
        # Add this result to the report collection.
        reports['source_comparison'].append(result)
    for name, rows in reports.items():
        # Export this report only when it contains records.
        if rows:
            # Collect all report column names.
            fields = list(dict.fromkeys(k for row in rows for k in row))
            # Open the output file and automatically close it after writing.
            with (args.output_dir / f'dq_{name}.csv').open('w', newline='', encoding='utf-8') as handle:
                # Create a CSV writer for the report.
                writer = csv.DictWriter(handle, fieldnames=fields)
                # Write the report column headings.
                writer.writeheader()
                # Write the report records.
                writer.writerows(rows)
    # Save the complete report as JSON.
    (args.output_dir / 'dq_report.json').write_text(
        json.dumps(reports, default=str, indent=2), encoding='utf-8')
    # Close the database connection.
    con.close()
    # Show progress or results in the terminal.
    print(f'Reports saved to {args.output_dir}', flush=True)


# Run this section only when the script is executed directly.
if __name__ == '__main__':
    # Build and export the data quality reports.
    main()
