"""Run all SQL checks on the simulated dataset (DuckDB). Run from the repository root:  python sql/run_checks.py"""
import glob, duckdb
for path in sorted(glob.glob("sql/0*.sql")):
    df = duckdb.sql(open(path).read()).df()
    print(f"\n=== {path}  ({len(df)} rows)")
    print(df.to_string(index=False) if len(df) else "No rows returned: nothing flagged.")
