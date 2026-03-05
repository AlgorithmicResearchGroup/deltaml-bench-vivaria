#!/usr/bin/env python3
"""
Analyze Vivaria run times from creation to completion (submission or error)
"""
import argparse
import json
import subprocess
from datetime import datetime
from typing import List, Dict, Any

def get_runs_from_db(limit: int = None, status_filter: str = None) -> List[Dict[str, Any]]:
    """Fetch run information from the database"""

    # SQL query to get run times - takes the first completed branch for each run
    where_clause = ""
    if status_filter == "submitted":
        where_clause = "AND submission IS NOT NULL AND LENGTH(submission) > 0"
    elif status_filter == "error":
        where_clause = 'AND "fatalError" IS NOT NULL'
    elif status_filter == "running":
        where_clause = 'AND "completedAt" IS NULL'

    limit_clause = f"LIMIT {limit}" if limit else ""

    query = f"""
    WITH ranked_branches AS (
        SELECT
            r.id as run_id,
            r.name as run_name,
            r."createdAt",
            ab."completedAt",
            ab.submission,
            ab.score,
            ab."fatalError",
            ROW_NUMBER() OVER (PARTITION BY r.id ORDER BY ab."completedAt" ASC NULLS LAST) as rn
        FROM runs_t r
        LEFT JOIN agent_branches_t ab ON r.id = ab."runId"
    )
    SELECT
        run_id,
        run_name,
        "createdAt",
        "completedAt",
        submission,
        score,
        "fatalError",
        CASE
            WHEN "completedAt" IS NOT NULL THEN
                ("completedAt" - "createdAt") / 1000.0
            ELSE NULL
        END as duration_seconds,
        CASE
            WHEN submission IS NOT NULL AND LENGTH(submission) > 0 THEN 'submitted'
            WHEN "fatalError" IS NOT NULL THEN 'error'
            WHEN "completedAt" IS NOT NULL THEN 'completed'
            ELSE 'running'
        END as status
    FROM ranked_branches
    WHERE (rn = 1 OR "completedAt" IS NULL) {where_clause}
    ORDER BY run_id DESC
    {limit_clause}
    """

    # Run the query using docker exec - use | as delimiter to avoid issues with tabs in content
    cmd = [
        'sudo', 'docker', 'exec', 'vivaria-database-1',
        'psql', '-U', 'vivaria', '-d', 'vivaria', '-t', '-A', '-F', '|',
        '-c', query
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        lines = result.stdout.strip().split('\n')

        if status_filter == "submitted":
            print(f"Debug: Query returned {len(lines)} lines")

        runs = []
        for line in lines:
            if not line:
                continue
            parts = line.split('|')
            if len(parts) >= 9:
                runs.append({
                    'run_id': int(parts[0]) if parts[0] else None,
                    'run_name': parts[1],
                    'created_at': parts[2],
                    'completed_at': parts[3] if parts[3] else None,
                    'submission': parts[4] if parts[4] else None,
                    'score': float(parts[5]) if parts[5] and parts[5] != '\\N' else None,
                    'has_error': parts[6] != '\\N' and parts[6],
                    'duration_seconds': float(parts[7]) if parts[7] and parts[7] != '\\N' else None,
                    'status': parts[8]
                })

        return runs
    except subprocess.CalledProcessError as e:
        print(f"Database query failed: {e}")
        print(f"Error output: {e.stderr}")
        print(f"Stdout: {e.stdout}")
        raise

def format_duration(seconds: float) -> str:
    """Format duration in seconds to human-readable string"""
    if seconds is None:
        return "N/A"

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"

def print_runs_table(runs: List[Dict[str, Any]], verbose: bool = False):
    """Print runs in a formatted table"""

    # Separate runs by status
    submitted_runs = [r for r in runs if r['status'] == 'submitted' and r['duration_seconds'] is not None]
    error_runs = [r for r in runs if r['status'] == 'error']
    running_runs = [r for r in runs if r['status'] == 'running']
    completed_runs = [r for r in runs if r['duration_seconds'] is not None]

    print("\n" + "="*80)
    print("RUN STATISTICS")
    print("="*80)
    print(f"Total runs analyzed: {len(runs)}")
    print()

    # Success vs Error counts
    print("COMPLETION STATUS:")
    print(f"  ✓ Successfully submitted: {len(submitted_runs)}")
    print(f"  ✗ Failed with error: {len(error_runs)}")
    print(f"  ⋯ Still running: {len(running_runs)}")

    if completed_runs:
        success_rate = (len(submitted_runs) / len(completed_runs)) * 100
        print(f"\n  Success Rate: {success_rate:.1f}% ({len(submitted_runs)}/{len(completed_runs)})")
    print()

    # Statistics for successful submissions only
    if submitted_runs:
        durations = [r['duration_seconds'] for r in submitted_runs]
        avg_duration = sum(durations) / len(durations)
        min_duration = min(durations)
        max_duration = max(durations)

        print("SUCCESSFUL SUBMISSION TIMES:")
        print(f"  Average time to submission: {format_duration(avg_duration)}")
        print(f"  Fastest submission: {format_duration(min_duration)}")
        print(f"  Slowest submission: {format_duration(max_duration)}")

        # Show scores for submitted runs
        scores = [r['score'] for r in submitted_runs if r['score'] is not None]
        if scores:
            avg_score = sum(scores) / len(scores)
            print(f"\n  Average score: {avg_score:.2f}")
            print(f"  Score range: {min(scores):.2f} - {max(scores):.2f}")
    else:
        print("SUCCESSFUL SUBMISSION TIMES:")
        print("  No successful submissions to analyze")
    print()

    # Print detailed table
    print("="*80)
    print(f"{'ID':<6} {'Name':<30} {'Status':<12} {'Duration':<12} {'Score':<8}")
    print("-"*80)

    for run in runs:
        run_id = run['run_id']
        name = run['run_name'][:28] + '..' if len(run['run_name']) > 30 else run['run_name']
        status = run['status']
        duration = format_duration(run['duration_seconds'])
        score = f"{run['score']:.2f}" if run['score'] is not None else "N/A"

        # Color coding for status
        if status == 'submitted':
            status_str = f"✓ {status}"
        elif status == 'error':
            status_str = f"✗ {status}"
        elif status == 'running':
            status_str = f"⋯ {status}"
        else:
            status_str = status

        print(f"{run_id:<6} {name:<30} {status_str:<12} {duration:<12} {score:<8}")

        if verbose and (run['submission'] or run['has_error']):
            if run['submission']:
                print(f"       Submission: {run['submission'][:70]}...")
            if run['has_error']:
                print(f"       Error: Fatal error occurred")

    print("="*80)

    # Print JSON for programmatic use if requested
    if verbose:
        print("\nJSON output for programmatic use:")
        json_runs = []
        for run in completed_runs:
            json_runs.append({
                'run_id': run['run_id'],
                'name': run['run_name'],
                'status': run['status'],
                'duration_seconds': run['duration_seconds'],
                'duration_formatted': format_duration(run['duration_seconds']),
                'score': run['score']
            })
        print(json.dumps(json_runs, indent=2))

def main():
    parser = argparse.ArgumentParser(description='Analyze Vivaria run completion times')
    parser.add_argument('--limit', type=int, default=None,
                        help='Number of recent runs to analyze (default: no limit)')
    parser.add_argument('--verbose', action='store_true',
                        help='Show additional details and JSON output')
    parser.add_argument('--status', choices=['all', 'submitted', 'error', 'running'],
                        default='all', help='Filter by run status')
    parser.add_argument('--submitted-only', action='store_true',
                        help='Show only successfully submitted runs')

    args = parser.parse_args()

    # Fetch runs from database with appropriate filter
    if args.submitted_only:
        runs = get_runs_from_db(limit=args.limit, status_filter='submitted')
    elif args.status != 'all':
        runs = get_runs_from_db(limit=args.limit, status_filter=args.status)
    else:
        runs = get_runs_from_db(limit=args.limit)

    if not runs:
        print("No runs found matching criteria")
        return

    # Print results
    print_runs_table(runs, verbose=args.verbose)

if __name__ == '__main__':
    main()