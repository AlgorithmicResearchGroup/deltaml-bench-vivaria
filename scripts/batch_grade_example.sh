#!/bin/bash
#
# Example script for batch grading multiple Vivaria runs (with parallel execution)
# Usage: ./batch_grade_example.sh

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRADE_SCRIPT="${SCRIPT_DIR}/grade_agent_logs_db.py"
RESULTS_DIR="${SCRIPT_DIR}/grading_results"
MAX_PARALLEL=5  # Number of jobs to run in parallel

# Create results directory if it doesn't exist
mkdir -p "${RESULTS_DIR}"

# Example run IDs to grade (replace with your actual run IDs)
RUN_IDS=(
    129
    130
    131
    134
    139
)

# Note: OpenAI API key check removed - the Python script has a default fallback

# Check if run IDs are provided
if [ ${#RUN_IDS[@]} -eq 0 ]; then
    echo "No run IDs specified. Please edit this script and add run IDs to the RUN_IDS array."
    exit 1
fi

TOTAL_RUNS=${#RUN_IDS[@]}

echo "=========================================="
echo "Batch Grading ${TOTAL_RUNS} Vivaria Runs"
echo "Parallel jobs: ${MAX_PARALLEL}"
echo "Results will be saved to: ${RESULTS_DIR}"
echo "=========================================="
echo

# Function to grade a single run
grade_run() {
    local run_id=$1
    local log_file="${RESULTS_DIR}/run_${run_id}_logs.txt"
    local result_file="${RESULTS_DIR}/run_${run_id}_result.json"
    local status_file="${RESULTS_DIR}/run_${run_id}_status.txt"

    # Run the grading script
    if python "${GRADE_SCRIPT}" \
        --run-id "${run_id}" \
        --save-logs "${log_file}" \
        --json > "${result_file}" 2>&1; then

        # Check the actual result from JSON
        if grep -q '"result"' "${result_file}"; then
            RESULT=$(python -c "import json; print(json.load(open('${result_file}'))['result'])" 2>/dev/null || echo "ERROR")
            REASONING=$(python -c "import json; print(json.load(open('${result_file}'))['reasoning'])" 2>/dev/null || echo "")

            if [ "${RESULT}" == "PASS" ]; then
                echo "PASSED" > "${status_file}"
                echo "[$(date '+%H:%M:%S')] ✓ Run ${run_id}: PASSED"
                echo "  Reasoning: ${REASONING}"
            else
                echo "FAILED" > "${status_file}"
                echo "[$(date '+%H:%M:%S')] ✗ Run ${run_id}: FAILED"
                echo "  Reasoning: ${REASONING}"
            fi
        else
            echo "ERROR" > "${status_file}"
            echo "[$(date '+%H:%M:%S')] ! Run ${run_id}: ERROR (malformed output)"
        fi
    else
        echo "ERROR" > "${status_file}"
        # Try to extract error message
        ERROR_MSG=$(head -1 "${result_file}" 2>/dev/null || echo "Unknown error")
        echo "[$(date '+%H:%M:%S')] ! Run ${run_id}: ERROR"
        echo "  Error: ${ERROR_MSG}"
    fi
    echo
}

# Process runs in parallel batches
for run_id in "${RUN_IDS[@]}"; do
    # Wait if we've hit the parallel limit
    while [ $(jobs -r | wc -l) -ge ${MAX_PARALLEL} ]; do
        sleep 1
    done

    # Start grading this run in background
    grade_run "${run_id}" &
done

# Wait for all background jobs to complete
echo "Waiting for all grading jobs to complete..."
wait

echo "=========================================="
echo "Grading Complete!"
echo "=========================================="

# Count results
PASSED=0
FAILED=0
ERRORS=0

for run_id in "${RUN_IDS[@]}"; do
    STATUS_FILE="${RESULTS_DIR}/run_${run_id}_status.txt"
    if [ -f "${STATUS_FILE}" ]; then
        STATUS=$(cat "${STATUS_FILE}")
        if [ "${STATUS}" == "PASSED" ]; then
            ((PASSED++))
        elif [ "${STATUS}" == "FAILED" ]; then
            ((FAILED++))
        else
            ((ERRORS++))
        fi
    else
        ((ERRORS++))
    fi
done

echo "Total Runs: ${TOTAL_RUNS}"
echo "Passed:     ${PASSED}"
echo "Failed:     ${FAILED}"
echo "Errors:     ${ERRORS}"
echo
echo "Results saved in: ${RESULTS_DIR}"

# Generate summary CSV
SUMMARY_FILE="${RESULTS_DIR}/summary.csv"
echo "run_id,result,reasoning" > "${SUMMARY_FILE}"

for run_id in "${RUN_IDS[@]}"; do
    RESULT_FILE="${RESULTS_DIR}/run_${run_id}_result.json"
    if [ -f "${RESULT_FILE}" ] && grep -q '"result"' "${RESULT_FILE}"; then
        RESULT=$(python -c "import json; print(json.load(open('${RESULT_FILE}'))['result'])" 2>/dev/null || echo "ERROR")
        REASONING=$(python -c "import json; print(json.load(open('${RESULT_FILE}'))['reasoning'].replace(',', ';'))" 2>/dev/null || echo "")
        echo "${run_id},${RESULT},\"${REASONING}\"" >> "${SUMMARY_FILE}"
    else
        echo "${run_id},ERROR,\"No valid result\"" >> "${SUMMARY_FILE}"
    fi
done

echo "Summary CSV saved to: ${SUMMARY_FILE}"

# Clean up status files
rm -f "${RESULTS_DIR}"/run_*_status.txt

# Exit with appropriate code
if [ ${ERRORS} -gt 0 ]; then
    exit 2
elif [ ${FAILED} -gt 0 ]; then
    exit 1
else
    exit 0
fi
