#!/bin/bash
# Run Manager for RE-Bench Tasks
# Smart manager for running and monitoring Vivaria jobs on RE-Bench tasks

# Attempt to activate conda environment at the start
if command -v conda &>/dev/null; then
    source "$(conda info --base)/etc/profile.d/conda.sh" && conda activate rebench &>/dev/null || true
fi

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
# Default agent path, can be overridden with --agent flag
AGENT_PATH="$PROJECT_DIR/modular-public"
REBENCH_DIR="$PROJECT_DIR/RE-Bench"
ENV_FILE="$PROJECT_DIR/.env"
LOGS_DIR="$PROJECT_DIR/vivaria_logs"
JOBS_DIR="$PROJECT_DIR/vivaria_jobs"
MAX_TOKENS="10000000"
MAX_ACTIONS="3000"
# Default max runtime (7 days = 604800 seconds), can be overridden with --timeout flag
MAX_TOTAL_SECONDS="604800"
# Default number of times to run a task, can be overridden with --times flag
RUN_COUNT=1

# Colors for pretty output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Available RE-Bench tasks
AVAILABLE_TASKS=(
    # AI R&D Tasks
    "ai_rd_fix_embedding"
    "ai_rd_nanogpt_chat_rl"
    "ai_rd_optimize_llm_foundry"
    "ai_rd_restricted_mlm"
    "ai_rd_rust_codecontests_inference"
    "ai_rd_small_scaling_law"
    "ai_rd_triton_cumsum"
    
    # PWC Tasks (Papers with Code - converted to RE-Bench format)
    "pwc_5_datasets_code_cl"
    "pwc_astock_srl_factors"
    "pwc_btad_urd"
    "pwc_california_housing_binary_diffusion"
    "pwc_cat2000_sum"
    "pwc_chameleon_coed"
    "pwc_cifar_100_pro_dsc"
    "pwc_cifar_10_abnet_2g_r0"
    "pwc_cifar_10_resnet18_fsgdm"
    "pwc_clintox_bilstm"
    "pwc_electricity_192_cyclenet"
    "pwc_etth1_336_multivariate_softs"
    "pwc_etth1_720_multivariate_sparsetsf"
    "pwc_fashion_mnist_continued_fraction_of_straight_lines"
    "pwc_fashion_mnist_energize"
    "pwc_fashion_mnist_gecco"
    "pwc_fb15k_237_dabr"
    "pwc_fer2013_vgg_based"
    "pwc_gowalla_rlae_dan"
    "pwc_hme100k_ical"
    "pwc_imagenet_10_dpac"
    "pwc_istd_rasm"
    "pwc_kvasir_seg_effisegnet_b5"
    "pwc_kvasir_seg_emcad"
    "pwc_kvasir_seg_yolo_sam_2"
    "pwc_malnet_tiny_gatedgcn"
    "pwc_mimic_iii_fld"
    "pwc_mm_vet_flashsloth_hd"
    "pwc_mnist_gatedgcn"
    "pwc_office_31_euda"
    "pwc_ogbg_molhiv_gatedgcn"
    "pwc_ogbl_ddi_gcn_node_embedding"
    "pwc_pdbbind_bapulm"
    "pwc_pemsd4_pm_dmnet_r"
    "pwc_peptides_struct_gcn"
    "pwc_stanford_cars_prometar"
    "pwc_summe_csta"
    "pwc_tiny_imagenet_pro_dsc"
    "pwc_traffic_glinear"
    "pwc_training_and_validation_dataset_of_capsule_vision_2024_challenge_biomedclip_pubmedbert"
    "pwc_txl_pbc_a_freely_accessible_labeled_peripheral_blood_cell_dataset_yolov5n"
    "pwc_ucr_anomaly_archive_kan"
    "pwc_weather_192_xpatch"
    "pwc_wigesture_csi_bert"
    "pwc_york_urban_dataset_dt_lsd"
    "pwc_zju_rgb_p_csfnet_2"
    "pwc_cnn"
    "pwc_digital_twin_supported_deep_learning_for_fault_diagnosis_dann"
    "pwc_etth1_336_multivariate_amd"
    "pwc_food_101_mano_tiny"
    "pwc_mnist_rkan"
    "pwc_stl_10_40_labels_semioccam"
    "pwc_tiny_imagenet_classification_mano_tiny"
    "pwc_zinc_neuralwalker"
)

# Create required directories
mkdir -p "$LOGS_DIR" "$JOBS_DIR"

# Helper functions
print_header() {
    echo -e "${BLUE}=========================================${NC}"
    echo -e "${BLUE}    RE-Bench Run Manager${NC}"
    echo -e "${BLUE}=========================================${NC}"
}

validate_environment() {
    local errors=0
    
    # Check required directories
    if [[ ! -d "$PROJECT_DIR" ]]; then
        echo -e "${RED}Error: Project directory not found: $PROJECT_DIR${NC}"
        ((errors++))
    fi
    
    if [[ ! -d "$AGENT_PATH" ]]; then
        echo -e "${RED}Error: Agent path not found: $AGENT_PATH${NC}"
        ((errors++))
    fi
    
    if [[ ! -d "$REBENCH_DIR" ]]; then
        echo -e "${RED}Error: RE-Bench directory not found: $REBENCH_DIR${NC}"
        ((errors++))
    fi
    
    if [[ ! -f "$ENV_FILE" ]]; then
        echo -e "${RED}Error: Environment file not found: $ENV_FILE${NC}"
        echo -e "${YELLOW}Note: Create a repo-local .env file or pass env vars directly to Vivaria.${NC}"
        ((errors++))
    fi
    
    # Check if viv command is available
    if ! command -v viv &> /dev/null; then
        echo -e "${RED}Error: 'viv' command not found. Please ensure Vivaria CLI is installed and in PATH${NC}"
        ((errors++))
    fi
    
    return $errors
}

print_task_list() {
    echo -e "${CYAN}Available RE-Bench tasks:${NC}"
    for i in "${!AVAILABLE_TASKS[@]}"; do
        local task="${AVAILABLE_TASKS[$i]}"
        local status=$(get_task_status "$task")
        printf "%2d) ${GREEN}%-35s${NC} %s\n" $((i+1)) "$task" "$status"
    done
}

get_task_description() {
    local task="$1"
    local readme_file="$REBENCH_DIR/${task}/README.md"
    if [[ -f "$readme_file" ]]; then
        # Extract first line of description from README
        head -5 "$readme_file" | grep -E "^[A-Z]" | head -1 | cut -c1-80 || echo "No description available"
    else
        echo "README not found"
    fi
}

get_task_status() {
    local task="$1"
    local job_file="$JOBS_DIR/${task}.job"
    
    if [[ -f "$job_file" ]]; then
        local run_id=$(cat "$job_file")
        local status=$(get_vivaria_run_status "$run_id" 2>/dev/null || echo "unknown")
        case "$status" in
            "running") echo -e "${GREEN}[RUNNING #$run_id]${NC}" ;;
            "submitted") echo -e "${BLUE}[COMPLETED #$run_id]${NC}" ;;
            "killed") echo -e "${RED}[KILLED #$run_id]${NC}" ;;
            "error") echo -e "${RED}[ERROR #$run_id]${NC}" ;;
            "queued") echo -e "${YELLOW}[QUEUED #$run_id]${NC}" ;;
            "setting-up") echo -e "${YELLOW}[SETTING UP #$run_id]${NC}" ;;
            *) echo -e "${PURPLE}[UNKNOWN #$run_id]${NC}" ;;
        esac
    else
        echo -e "${CYAN}[NOT STARTED]${NC}"
    fi
}

get_vivaria_run_status() {
    local run_id="$1"
    # Try multiple methods to get run status
    
    # Method 1: Try viv status if available  
    if command -v viv &> /dev/null; then
        # Try getting status for the specific run
        local status_output=$(viv status "$run_id" 2>/dev/null || echo "")
        if [[ -n "$status_output" ]]; then
            # Extract status from the output
            echo "$status_output" | grep -oE "(running|submitted|killed|error|queued|setting-up|paused)" | head -1 || echo "unknown"
            return
        fi
        
        # Fallback: try listing all runs and find this one
        local list_output=$(viv runs 2>/dev/null | grep -E "^.*$run_id" | head -1 || echo "")
        if [[ -n "$list_output" ]]; then
            echo "$list_output" | grep -oE "(running|submitted|killed|error|queued|setting-up|paused)" | head -1 || echo "unknown"
            return
        fi
    fi
    
    # Method 2: Default fallback - assume running if job file exists and wasn't cleaned up
    echo "unknown"
}

start_single_task() {
    local task="$1"
    local run_name="$2"
    local run_number="${3:-1}"
    
    # Check if job is already running (but only for single runs to avoid conflicts)
    if [[ "$RUN_COUNT" -eq 1 ]]; then
        local job_file="$JOBS_DIR/${task}.job"
        if [[ -f "$job_file" ]]; then
            local existing_run_id=$(cat "$job_file")
            local status=$(get_vivaria_run_status "$existing_run_id" 2>/dev/null || echo "unknown")
            if [[ "$status" == "running" || "$status" == "queued" || "$status" == "setting-up" ]]; then
                echo -e "${YELLOW}Warning: Task '$task' already has a running job (Run #$existing_run_id)${NC}"
                echo -e "Use '${CYAN}$0 status $task${NC}' to check status or '${CYAN}$0 kill $task${NC}' to stop it."
                return 1
            fi
        fi
    fi
    
    local task_dir="$REBENCH_DIR/$task"
    
    echo -e "${GREEN}Starting Vivaria job for task: $task (run $run_number)${NC}"
    echo -e "${BLUE}Run name: $run_name${NC}"
    echo -e "${PURPLE}Description: $(get_task_description "$task")${NC}"
    echo -e "${CYAN}Command: viv run --agent-path $AGENT_PATH --task-family-path $task_dir --env-file-path $ENV_FILE --max_tokens $MAX_TOKENS --max_actions $MAX_ACTIONS --max_total_seconds $MAX_TOTAL_SECONDS --intervention True ${task}/main${NC}"
    echo
    
    # Create log file with run number for multiple runs
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local log_file
    if [[ "$RUN_COUNT" -gt 1 ]]; then
        log_file="$LOGS_DIR/${task}_run${run_number}_${timestamp}.log"
    else
        log_file="$LOGS_DIR/${task}_${timestamp}.log"
    fi
    
    # Start the Vivaria job
    echo "Starting Vivaria job at $(date)" > "$log_file"
    echo "Task: $task" >> "$log_file"
    echo "Run name: $run_name" >> "$log_file"
    echo "Command: viv run --agent-path $AGENT_PATH --task-family-path $task_dir --env-file-path $ENV_FILE --max_tokens $MAX_TOKENS --max_actions $MAX_ACTIONS --max_total_seconds $MAX_TOTAL_SECONDS --intervention True ${task}/main" >> "$log_file"
    echo "========================================" >> "$log_file"
    
    # Run the command and capture output
    local output
    if output=$(viv run \
        --agent-path "$AGENT_PATH" \
        --task-family-path "$task_dir" \
        --env-file-path "$ENV_FILE" \
        --max_tokens "$MAX_TOKENS" \
        --max_actions "$MAX_ACTIONS" \
        --max_total_seconds "$MAX_TOTAL_SECONDS" \
        --intervention True \
        --name "$run_name" \
        "${task}/main" 2>&1); then
        
        echo "$output" >> "$log_file"
        
        # Extract run ID from output (Vivaria outputs just the number and URL)
        local run_id=$(echo "$output" | grep -oE "^[0-9]+$" | head -1 || echo "$output" | grep -oE "run/#[0-9]+" | head -1 | sed 's/run\/#//' || echo "unknown")
        
        if [[ "$run_id" != "unknown" && "$run_id" != "" ]]; then
            # For multiple runs, store job files with run numbers
            local job_file
            if [[ "$RUN_COUNT" -gt 1 ]]; then
                job_file="$JOBS_DIR/${task}_run${run_number}.job"
            else
                job_file="$JOBS_DIR/${task}.job"
            fi
            echo "$run_id" > "$job_file"
            
            echo -e "${GREEN}✓ Job started successfully!${NC}"
            echo -e "${BLUE}Run ID: $run_id${NC}"
            echo -e "${BLUE}Log file: $log_file${NC}"
            
            if [[ "$RUN_COUNT" -eq 1 ]]; then
                echo -e "Monitor with: ${CYAN}$0 monitor $task${NC}"
                echo -e "Check status: ${CYAN}$0 status $task${NC}"
            fi
            
            # Extract and display the run URL if available
            local run_url=$(echo "$output" | grep -E "^https?://" | head -1 | tr -d '\r\n')
            if [[ -n "$run_url" ]]; then
                echo -e "${PURPLE}Run URL: $run_url${NC}"
            fi
        else
            echo -e "${YELLOW}Warning: Could not extract run ID from output${NC}"
            echo -e "${BLUE}Check log file: $log_file${NC}"
        fi
    else
        echo "$output" >> "$log_file"
        echo -e "${RED}✗ Failed to start job${NC}"
        echo -e "${BLUE}Check log file: $log_file${NC}"
        return 1
    fi
}

start_task() {
    local task="$1"
    local run_name_base="${2:-${task}_$(date +%Y%m%d_%H%M%S)}"
    
    # Validate environment first
    if ! validate_environment; then
        return 1
    fi
    
    # Check if task exists
    if [[ ! " ${AVAILABLE_TASKS[@]} " =~ " $task " ]]; then
        echo -e "${RED}Error: Unknown task '$task'${NC}"
        print_task_list
        return 1
    fi
    
    # Check if task directory exists
    local task_dir="$REBENCH_DIR/$task"
    if [[ ! -d "$task_dir" ]]; then
        echo -e "${RED}Error: Task directory not found: $task_dir${NC}"
        return 1
    fi
    
    if [[ "$RUN_COUNT" -gt 1 ]]; then
        echo -e "${YELLOW}Starting task '$task' $RUN_COUNT times...${NC}"
        echo
        
        local success_count=0
        local failed_count=0
        
        for ((i=1; i<=RUN_COUNT; i++)); do
            echo -e "${CYAN}========== Run $i of $RUN_COUNT ==========${NC}"
            
            # Create unique run name for each iteration
            local run_name="${run_name_base}_run${i}"
            
            # Temporarily disable exit on error for individual runs
            set +e
            if start_single_task "$task" "$run_name" "$i"; then
                ((success_count++))
                echo -e "${GREEN}✓ Run $i completed successfully${NC}"
            else
                ((failed_count++))
                echo -e "${RED}✗ Run $i failed${NC}"
            fi
            set -e
            
            # Add delay between runs to avoid overwhelming the system
            if [[ $i -lt $RUN_COUNT ]]; then
                echo -e "${YELLOW}Waiting 5 seconds before next run...${NC}"
                sleep 5
                echo
            fi
        done
        
        echo -e "\n${CYAN}========== Summary ==========${NC}"
        echo -e "Total runs: $RUN_COUNT"
        echo -e "Successful: $success_count"
        echo -e "Failed: $failed_count"
        
        if [[ $success_count -gt 0 ]]; then
            echo -e "\n${YELLOW}Monitor all runs with:${NC}"
            for ((i=1; i<=RUN_COUNT; i++)); do
                local job_file="$JOBS_DIR/${task}_run${i}.job"
                if [[ -f "$job_file" ]]; then
                    local run_id=$(cat "$job_file")
                    echo -e "  Run $i (ID: $run_id): ${CYAN}viv status $run_id${NC}"
                fi
            done
        fi
    else
        # Single run
        start_single_task "$task" "$run_name_base" 1
    fi
}

start_all_tasks() {
    echo -e "${YELLOW}Starting ALL RE-Bench tasks...${NC}"
    
    if ! validate_environment; then
        return 1
    fi
    
    local started=0
    local skipped=0
    local failed=0
    
    for task in "${AVAILABLE_TASKS[@]}"; do
        echo -e "\n${CYAN}Processing task: $task${NC}"
        
        # Check if already running
        local job_file="$JOBS_DIR/${task}.job"
        if [[ -f "$job_file" ]]; then
            local existing_run_id=$(cat "$job_file")
            # Temporarily disable exit on error for status check
            set +e
            local status=$(get_vivaria_run_status "$existing_run_id" 2>/dev/null || echo "unknown")
            set -e
            if [[ "$status" == "running" || "$status" == "queued" || "$status" == "setting-up" ]]; then
                echo -e "${YELLOW}Skipping $task (already running: #$existing_run_id)${NC}"
                ((skipped++))
                continue
            fi
        fi
        
        # Temporarily disable exit on error for this task
        set +e
        if start_task "$task" "${task}_batch_$(date +%Y%m%d_%H%M%S)"; then
            ((started++))
            echo -e "${GREEN}✓ Started $task${NC}"
            # Brief delay between starts to avoid overwhelming the system
            sleep 5
        else
            echo -e "${RED}✗ Failed to start $task${NC}"
            ((failed++))
        fi
        # Re-enable exit on error
        set -e
    done
    
    echo -e "\n${GREEN}✓ Batch operation complete!${NC}"
    echo -e "Started: $started tasks"
    echo -e "Skipped: $skipped tasks"
    echo -e "Failed: $failed tasks"
}

start_all_pwc_tasks() {
    echo -e "${YELLOW}Starting ALL PWC tasks...${NC}"
    
    if ! validate_environment; then
        return 1
    fi
    
    local started=0
    local skipped=0
    local failed=0
    
    for task in "${AVAILABLE_TASKS[@]}"; do
        # Skip non-PWC tasks
        if [[ ! "$task" =~ ^pwc_ ]]; then
            continue
        fi
        
        echo -e "\n${CYAN}Processing task: $task${NC}"
        
        # Check if already running
        local job_file="$JOBS_DIR/${task}.job"
        if [[ -f "$job_file" ]]; then
            local existing_run_id=$(cat "$job_file")
            # Temporarily disable exit on error for status check
            set +e
            local status=$(get_vivaria_run_status "$existing_run_id" 2>/dev/null || echo "unknown")
            set -e
            if [[ "$status" == "running" || "$status" == "queued" || "$status" == "setting-up" ]]; then
                echo -e "${YELLOW}Skipping $task (already running: #$existing_run_id)${NC}"
                ((skipped++))
                continue
            fi
        fi
        
        # Temporarily disable exit on error for this task
        set +e
        if start_task "$task" "${task}_batch_$(date +%Y%m%d_%H%M%S)"; then
            ((started++))
            echo -e "${GREEN}✓ Started $task${NC}"
            # Brief delay between starts to avoid overwhelming the system
            sleep 5
        else
            echo -e "${RED}✗ Failed to start $task${NC}"
            ((failed++))
        fi
        # Re-enable exit on error
        set -e
    done
    
    echo -e "\n${GREEN}✓ PWC batch operation complete!${NC}"
    echo -e "Started: $started tasks"
    echo -e "Skipped: $skipped tasks"
    echo -e "Failed: $failed tasks"
}

start_all_ai_rd_tasks() {
    echo -e "${YELLOW}Starting ALL AI R&D tasks...${NC}"
    
    if ! validate_environment; then
        return 1
    fi
    
    local started=0
    local skipped=0
    local failed=0
    
    for task in "${AVAILABLE_TASKS[@]}"; do
        # Skip non-AI R&D tasks
        if [[ ! "$task" =~ ^ai_rd_ ]]; then
            continue
        fi
        
        echo -e "\n${CYAN}Processing task: $task${NC}"
        
        # Check if already running
        local job_file="$JOBS_DIR/${task}.job"
        if [[ -f "$job_file" ]]; then
            local existing_run_id=$(cat "$job_file")
            # Temporarily disable exit on error for status check
            set +e
            local status=$(get_vivaria_run_status "$existing_run_id" 2>/dev/null || echo "unknown")
            set -e
            if [[ "$status" == "running" || "$status" == "queued" || "$status" == "setting-up" ]]; then
                echo -e "${YELLOW}Skipping $task (already running: #$existing_run_id)${NC}"
                ((skipped++))
                continue
            fi
        fi
        
        # Temporarily disable exit on error for this task
        set +e
        if start_task "$task" "${task}_batch_$(date +%Y%m%d_%H%M%S)"; then
            ((started++))
            echo -e "${GREEN}✓ Started $task${NC}"
            # Brief delay between starts to avoid overwhelming the system
            sleep 5
        else
            echo -e "${RED}✗ Failed to start $task${NC}"
            ((failed++))
        fi
        # Re-enable exit on error
        set -e
    done
    
    echo -e "\n${GREEN}✓ AI R&D batch operation complete!${NC}"
    echo -e "Started: $started tasks"
    echo -e "Skipped: $skipped tasks"
    echo -e "Failed: $failed tasks"
}

list_jobs() {
    echo -e "${CYAN}Current Vivaria jobs:${NC}"
    
    local active_jobs=0
    for task in "${AVAILABLE_TASKS[@]}"; do
        local job_file="$JOBS_DIR/${task}.job"
        if [[ -f "$job_file" ]]; then
            local run_id=$(cat "$job_file")
            local status=$(get_vivaria_run_status "$run_id" 2>/dev/null || echo "unknown")
            local status_color=""
            case "$status" in
                "running") status_color="${GREEN}" ;;
                "submitted") status_color="${BLUE}" ;;
                "killed"|"error") status_color="${RED}" ;;
                "queued"|"setting-up") status_color="${YELLOW}" ;;
                *) status_color="${PURPLE}" ;;
            esac
            echo -e "  ${GREEN}$task${NC} - Run #$run_id - ${status_color}$status${NC}"
            ((active_jobs++))
        fi
    done
    
    if [[ $active_jobs -eq 0 ]]; then
        echo -e "${YELLOW}No active jobs found.${NC}"
    fi
}

show_task_status() {
    local task="$1"
    
    if [[ -n "$task" ]]; then
        # Show status for specific task
        if [[ ! " ${AVAILABLE_TASKS[@]} " =~ " $task " ]]; then
            echo -e "${RED}Error: Unknown task '$task'${NC}"
            return 1
        fi
        
        local job_file="$JOBS_DIR/${task}.job"
        if [[ -f "$job_file" ]]; then
            local run_id=$(cat "$job_file")
            echo -e "${CYAN}Task: $task${NC}"
            echo -e "${BLUE}Run ID: $run_id${NC}"
            echo -e "${BLUE}Status: $(get_task_status "$task")${NC}"
            echo -e "${PURPLE}Description: $(get_task_description "$task")${NC}"
            
            # Show recent log entries
            local latest_log=$(ls -t "$LOGS_DIR/${task}_"*.log 2>/dev/null | head -1 || echo "")
            if [[ -n "$latest_log" ]]; then
                echo -e "${CYAN}Recent log entries:${NC}"
                tail -5 "$latest_log" | sed 's/^/  /'
            fi
        else
            echo -e "${YELLOW}Task '$task' has not been started yet.${NC}"
        fi
    else
        # Show status for all tasks
        print_header
        echo
        print_task_list
        echo
        list_jobs
    fi
}

kill_task() {
    local task="$1"
    
    if [[ ! " ${AVAILABLE_TASKS[@]} " =~ " $task " ]]; then
        echo -e "${RED}Error: Unknown task '$task'${NC}"
        return 1
    fi
    
    local job_file="$JOBS_DIR/${task}.job"
    if [[ ! -f "$job_file" ]]; then
        echo -e "${YELLOW}No active job found for task '$task'${NC}"
        return 1
    fi
    
    local run_id=$(cat "$job_file")
    echo -e "${YELLOW}Killing Vivaria job for task: $task (Run #$run_id)${NC}"
    
    # Kill the Vivaria run (adjust command based on actual viv CLI)
    if viv kill "$run_id" 2>/dev/null; then
        echo -e "${GREEN}✓ Job killed successfully${NC}"
        # Remove job file
        rm -f "$job_file"
    else
        echo -e "${RED}✗ Failed to kill job (it may have already finished)${NC}"
    fi
}

kill_all_jobs() {
    echo -e "${YELLOW}Killing all active Vivaria jobs...${NC}"
    
    local killed=0
    for task in "${AVAILABLE_TASKS[@]}"; do
        local job_file="$JOBS_DIR/${task}.job"
        if [[ -f "$job_file" ]]; then
            local run_id=$(cat "$job_file")
            echo -e "Killing $task (Run #$run_id)..."
            if viv kill "$run_id" 2>/dev/null; then
                echo -e "${GREEN}✓ Killed $task${NC}"
                rm -f "$job_file"
                ((killed++))
            else
                echo -e "${RED}✗ Failed to kill $task${NC}"
            fi
        fi
    done
    
    echo -e "${GREEN}✓ Killed $killed job(s)${NC}"
}

monitor_task() {
    local task="$1"
    
    if [[ ! " ${AVAILABLE_TASKS[@]} " =~ " $task " ]]; then
        echo -e "${RED}Error: Unknown task '$task'${NC}"
        return 1
    fi
    
    local job_file="$JOBS_DIR/${task}.job"
    if [[ ! -f "$job_file" ]]; then
        echo -e "${YELLOW}No active job found for task '$task'${NC}"
        return 1
    fi
    
    local run_id=$(cat "$job_file")
    echo -e "${GREEN}Monitoring task: $task (Run #$run_id)${NC}"
    echo -e "${YELLOW}Press Ctrl+C to stop monitoring${NC}"
    echo
    
    # Monitor job status
    while true; do
        local status=$(get_vivaria_run_status "$run_id" 2>/dev/null || echo "unknown")
        echo -e "$(date): Status = $status"
        
        case "$status" in
            "submitted"|"killed"|"error")
                echo -e "${BLUE}Job finished with status: $status${NC}"
                break
                ;;
        esac
        
        sleep 30
    done
}

show_logs() {
    local task="$1"
    
    if [[ -n "$task" ]]; then
        # Show logs for specific task
        if [[ ! " ${AVAILABLE_TASKS[@]} " =~ " $task " ]]; then
            echo -e "${RED}Error: Unknown task '$task'${NC}"
            return 1
        fi
        
        local latest_log=$(ls -t "$LOGS_DIR/${task}_"*.log 2>/dev/null | head -1 || echo "")
        if [[ -n "$latest_log" ]]; then
            echo -e "${GREEN}Showing latest log for $task:${NC}"
            echo -e "${BLUE}File: $latest_log${NC}"
            echo "================================="
            tail -f "$latest_log"
        else
            echo -e "${RED}No logs found for task: $task${NC}"
        fi
    else
        # List all available logs
        echo -e "${CYAN}Available log files:${NC}"
        ls -la "$LOGS_DIR"/*.log 2>/dev/null | tail -10 || echo "No log files found."
    fi
}

interactive_task_selection() {
    print_task_list
    echo
    read -p "Select task number (1-${#AVAILABLE_TASKS[@]}): " choice
    
    if [[ "$choice" =~ ^[0-9]+$ ]] && [[ "$choice" -ge 1 ]] && [[ "$choice" -le "${#AVAILABLE_TASKS[@]}" ]]; then
        local task="${AVAILABLE_TASKS[$((choice-1))]}"
        start_task "$task"
    else
        echo -e "${RED}Invalid selection!${NC}"
        return 1
    fi
}

cleanup_finished_jobs() {
    echo -e "${YELLOW}Cleaning up finished job files...${NC}"
    
    local cleaned=0
    for task in "${AVAILABLE_TASKS[@]}"; do
        local job_file="$JOBS_DIR/${task}.job"
        if [[ -f "$job_file" ]]; then
            local run_id=$(cat "$job_file")
            local status=$(get_vivaria_run_status "$run_id" 2>/dev/null || echo "unknown")
            
            case "$status" in
                "submitted"|"killed"|"error"|"unknown")
                    echo -e "Cleaning up $task (Run #$run_id, status: $status)"
                    rm -f "$job_file"
                    ((cleaned++))
                    ;;
            esac
        fi
    done
    
    echo -e "${GREEN}✓ Cleaned up $cleaned finished job(s)${NC}"
}

# Vivaria service management functions
get_vivaria_containers() {
    # Get list of Vivaria-related Docker containers
    docker ps -a --filter "name=vivaria" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo ""
}

check_vivaria_services_status() {
    echo -e "${CYAN}Vivaria Docker Services Status:${NC}"
    echo
    
    local containers_output=$(get_vivaria_containers)
    if [[ -z "$containers_output" || "$containers_output" == "NAMES	STATUS	PORTS" ]]; then
        echo -e "${RED}No Vivaria containers found.${NC}"
        echo -e "${YELLOW}Vivaria services may not be running or may not be Docker-based.${NC}"
        return 1
    fi
    
    echo "$containers_output"
    echo
    
    # Check if services are healthy
    local running_containers=$(docker ps --filter "name=vivaria" --filter "status=running" --format "{{.Names}}" 2>/dev/null | wc -l)
    local total_containers=$(docker ps -a --filter "name=vivaria" --format "{{.Names}}" 2>/dev/null | wc -l)
    
    if [[ $running_containers -eq $total_containers && $total_containers -gt 0 ]]; then
        echo -e "${GREEN}✓ All Vivaria services are running ($running_containers/$total_containers)${NC}"
    elif [[ $running_containers -gt 0 ]]; then
        echo -e "${YELLOW}⚠ Some Vivaria services are running ($running_containers/$total_containers)${NC}"
    else
        echo -e "${RED}✗ No Vivaria services are running (0/$total_containers)${NC}"
    fi
    
    # Check if viv command is accessible
    echo
    if command -v viv &> /dev/null; then
        echo -e "${GREEN}✓ viv command is available${NC}"
    else
        echo -e "${RED}✗ viv command not found (activate reb conda environment)${NC}"
    fi
}

stop_vivaria_services() {
    echo -e "${YELLOW}Stopping Vivaria services...${NC}"
    
    # Temporarily disable exit on error for this function
    set +e
    
    # Get list of running Vivaria containers
    local containers=$(docker ps --filter "name=vivaria" --format "{{.Names}}" 2>/dev/null)
    
    if [[ -z "$containers" ]]; then
        echo -e "${YELLOW}No running Vivaria containers found.${NC}"
        set -e
        return 0
    fi
    
    echo "Found running containers:"
    echo "$containers" | sed 's/^/  - /'
    echo
    
    # Stop each container using array instead of here-string
    local container_array=()
    while IFS= read -r line; do
        [[ -n "$line" ]] && container_array+=("$line")
    done <<< "$containers"
    
    local stopped=0
    local failed=0
    for container in "${container_array[@]}"; do
        echo -e "Stopping ${CYAN}$container${NC}..."
        if docker stop "$container" >/dev/null 2>&1; then
            echo -e "${GREEN}✓ Stopped $container${NC}"
            ((stopped++))
        else
            echo -e "${RED}✗ Failed to stop $container${NC}"
            ((failed++))
        fi
    done
    
    echo
    echo -e "${GREEN}✓ Operation complete: $stopped stopped, $failed failed${NC}"
    
    # Re-enable exit on error
    set -e
}

start_vivaria_services() {
    echo -e "${YELLOW}Starting Vivaria services...${NC}"
    
    # Temporarily disable exit on error for this function
    set +e
    
    # Get list of all Vivaria containers (including stopped ones)
    local containers=$(docker ps -a --filter "name=vivaria" --format "{{.Names}}" 2>/dev/null)
    
    if [[ -z "$containers" ]]; then
        echo -e "${RED}No Vivaria containers found.${NC}"
        echo -e "${YELLOW}You may need to run docker-compose up or equivalent to create the containers first.${NC}"
        set -e
        return 1
    fi
    
    echo "Found containers:"
    echo "$containers" | sed 's/^/  - /'
    echo
    
    # Start each container using array instead of here-string
    local container_array=()
    while IFS= read -r line; do
        [[ -n "$line" ]] && container_array+=("$line")
    done <<< "$containers"
    
    local started=0
    local failed=0
    for container in "${container_array[@]}"; do
        local status=$(docker ps -a --filter "name=$container" --format "{{.Status}}" 2>/dev/null)
        if [[ "$status" =~ ^Up ]]; then
            echo -e "${GREEN}$container is already running${NC}"
        else
            echo -e "Starting ${CYAN}$container${NC}..."
            if docker start "$container" >/dev/null 2>&1; then
                echo -e "${GREEN}✓ Started $container${NC}"
                ((started++))
            else
                echo -e "${RED}✗ Failed to start $container${NC}"
                ((failed++))
            fi
        fi
    done
    
    echo
    echo -e "${GREEN}✓ Operation complete: $started started, $failed failed${NC}"
    
    # Re-enable exit on error
    set -e
    
    # Wait a moment for services to initialize
    if [[ $started -gt 0 ]]; then
        echo -e "${YELLOW}Waiting for services to initialize...${NC}"
        sleep 5
        check_vivaria_services_status
    fi
}

restart_vivaria_services() {
    echo -e "${YELLOW}Restarting Vivaria services...${NC}"
    echo
    
    # Temporarily disable exit on error for this function
    set +e
    
    # First check current status
    echo -e "${CYAN}Current status:${NC}"
    check_vivaria_services_status
    echo
    
    # Stop services
    echo -e "${CYAN}Stopping services...${NC}"
    stop_vivaria_services
    local stop_result=$?
    echo
    
    # Wait a moment
    echo -e "${YELLOW}Waiting before restart...${NC}"
    sleep 3
    
    # Start services
    echo -e "${CYAN}Starting services...${NC}"
    start_vivaria_services
    local start_result=$?
    echo
    
    # Re-enable exit on error
    set -e
    
    if [[ $stop_result -eq 0 && $start_result -eq 0 ]]; then
        echo -e "${GREEN}✓ Vivaria services restart complete!${NC}"
    else
        echo -e "${YELLOW}⚠ Restart completed with some issues. Check status above.${NC}"
    fi
}

show_help() {
    print_header
    echo
    echo -e "${CYAN}Usage: $0 [--agent <path>] [--times <count>] [--timeout <seconds>] [command] [options]${NC}"
    echo
    echo -e "${YELLOW}Options:${NC}"
    echo -e "  ${GREEN}--agent <path>${NC}          Specify custom agent path"
    echo -e "  ${GREEN}--times <count>${NC}         Run task multiple times (default: 1)"
    echo -e "  ${GREEN}--timeout <seconds>${NC}     Auto-kill run after this many seconds (default: 604800 = 7 days)"
    echo -e "  ${GREEN}(default agent)${NC}         Use modular-public (default agent)"
    echo
    echo -e "${YELLOW}Job Management:${NC}"
    echo -e "  ${GREEN}start <task> [name]${NC}    Start a specific RE-Bench task"
    echo -e "  ${GREEN}start-all${NC}              Start all RE-Bench tasks"
    echo -e "  ${GREEN}start-all-pwc${NC}          Start all PWC tasks only"
    echo -e "  ${GREEN}start-all-ai-rd${NC}        Start all AI R&D tasks only"
    echo -e "  ${GREEN}kill <task>${NC}            Kill a specific task job"
    echo -e "  ${GREEN}kill-all${NC}               Kill all active jobs"
    echo -e "  ${GREEN}list${NC}                   List all active jobs"
    echo -e "  ${GREEN}status [task]${NC}          Show status (all tasks or specific)"
    echo -e "  ${GREEN}monitor <task>${NC}         Monitor a running task"
    echo -e "  ${GREEN}cleanup${NC}                Clean up finished job files"
    echo
    echo -e "${YELLOW}Vivaria Service Management:${NC}"
    echo -e "  ${GREEN}vivaria-status${NC}         Show Vivaria Docker services status"
    echo -e "  ${GREEN}restart-vivaria${NC}        Restart all Vivaria services"
    echo -e "  ${GREEN}stop-vivaria${NC}           Stop all Vivaria services"
    echo -e "  ${GREEN}start-vivaria${NC}          Start all Vivaria services"
    echo
    echo -e "${YELLOW}Logs & Information:${NC}"
    echo -e "  ${GREEN}logs [task]${NC}            Show logs (all or specific task)"
    echo -e "  ${GREEN}interactive${NC}            Interactive task selection"
    echo -e "  ${GREEN}tasks${NC}                  List available tasks"
    echo -e "  ${GREEN}help${NC}                   Show this help"
    echo
    echo -e "${CYAN}Available Tasks:${NC}"
    for task in "${AVAILABLE_TASKS[@]}"; do
        echo -e "  • $task"
    done
    echo
    echo -e "${CYAN}Examples:${NC}"
    echo -e "  ${YELLOW}Default Agent (modular-public):${NC}"
    echo -e "    $0 start ai_rd_triton_cumsum"
    echo -e "    $0 status ai_rd_triton_cumsum"
    echo -e "  ${YELLOW}Custom Agent:${NC}"
    echo -e "    $0 --agent ./arg_agent start ai_rd_triton_cumsum"
    echo -e "    $0 --agent ./arg_agent start ai_rd_fix_embedding my_custom_run"
    echo -e "    $0 --agent /path/to/my/agent status ai_rd_triton_cumsum"
    echo -e "    $0 --agent ./arg_agent start-all"
    echo -e "  ${YELLOW}Start All Tasks by Type:${NC}"
    echo -e "    $0 start-all-pwc                                      # Start all PWC tasks only"
    echo -e "    $0 start-all-ai-rd                                    # Start all AI R&D tasks only"
    echo -e "    $0 --agent ./arg_agent start-all-pwc                  # Start all PWC tasks with custom agent"
    echo -e "  ${YELLOW}Multiple Runs:${NC}"
    echo -e "    $0 --times 3 start ai_rd_triton_cumsum"
    echo -e "    $0 --agent ./arg_agent --times 5 start ai_rd_fix_embedding"
    echo -e "    $0 --times 10 --agent ./arg_agent start ai_rd_nanogpt_chat_rl batch_run"
    echo -e "  ${YELLOW}Time Limits (Auto-Kill):${NC}"
    echo -e "    $0 --timeout 3600 start ai_rd_triton_cumsum          # Kill after 1 hour"
    echo -e "    $0 --timeout 1800 start ai_rd_fix_embedding          # Kill after 30 minutes"
    echo -e "    $0 --agent ./arg_agent --timeout 7200 start pwc_mnist_gatedgcn  # Kill after 2 hours"
    echo -e "    $0 --times 3 --timeout 3600 start ai_rd_triton_cumsum  # 3 runs, each 1 hour max"
    echo -e "  ${YELLOW}Vivaria Services:${NC}"
    echo -e "    $0 vivaria-status"
    echo -e "    $0 restart-vivaria"
    echo -e "    $0 stop-vivaria"
    echo -e "    $0 start-vivaria"
    echo
    echo -e "${YELLOW}Configuration:${NC}"
    echo -e "  Agent path: ${CYAN}$AGENT_PATH${NC}"
    echo -e "  Run count: ${CYAN}$RUN_COUNT${NC}"
    echo -e "  Max runtime: ${CYAN}$MAX_TOTAL_SECONDS seconds ($(($MAX_TOTAL_SECONDS / 3600)) hours)${NC}"
    echo -e "  RE-Bench path: ${CYAN}$REBENCH_DIR${NC}"
    echo -e "  Env file: ${CYAN}$ENV_FILE${NC}"
    echo -e "  Max tokens: ${CYAN}$MAX_TOKENS${NC}"
    echo -e "  Max actions: ${CYAN}$MAX_ACTIONS${NC}"
    echo -e "  Logs: ${CYAN}$LOGS_DIR${NC}"
    echo -e "  Jobs: ${CYAN}$JOBS_DIR${NC}"
}

# Parse arguments for agent selection and run count
while [[ $# -gt 0 ]]; do
    case $1 in
        --agent)
            if [[ -n "$2" ]]; then
                AGENT_PATH="$2"
                shift 2
            else
                echo -e "${RED}Error: --agent requires a path argument${NC}"
                exit 1
            fi
            ;;
        --times)
            if [[ -n "$2" && "$2" =~ ^[0-9]+$ && "$2" -gt 0 ]]; then
                RUN_COUNT="$2"
                shift 2
            else
                echo -e "${RED}Error: --times requires a positive integer argument${NC}"
                exit 1
            fi
            ;;
        --timeout)
            if [[ -n "$2" && "$2" =~ ^[0-9]+$ && "$2" -gt 0 ]]; then
                MAX_TOTAL_SECONDS="$2"
                shift 2
            else
                echo -e "${RED}Error: --timeout requires a positive integer (seconds) argument${NC}"
                exit 1
            fi
            ;;
        *)
            break
            ;;
    esac
done

# Main command handling
case "${1:-help}" in
    "start")
        if [[ -z "$2" ]]; then
            echo -e "${RED}Error: Please specify a task name.${NC}"
            print_task_list
            exit 1
        fi
        start_task "$2" "$3"
        ;;
    
    "start-all")
        start_all_tasks
        ;;
    
    "start-all-pwc")
        start_all_pwc_tasks
        ;;
    
    "start-all-ai-rd"|"start-all-aird")
        start_all_ai_rd_tasks
        ;;
    
    "kill"|"stop")
        if [[ -z "$2" ]]; then
            echo -e "${RED}Error: Please specify a task name.${NC}"
            print_task_list
            exit 1
        fi
        kill_task "$2"
        ;;
    
    "kill-all"|"stop-all")
        kill_all_jobs
        ;;
    
    "list"|"ls")
        list_jobs
        ;;
    
    "status"|"st")
        show_task_status "$2"
        ;;
    
    "monitor"|"watch")
        if [[ -z "$2" ]]; then
            echo -e "${RED}Error: Please specify a task name.${NC}"
            print_task_list
            exit 1
        fi
        monitor_task "$2"
        ;;
    
    "logs"|"log")
        show_logs "$2"
        ;;
    
    "cleanup"|"clean")
        cleanup_finished_jobs
        ;;
    
    "interactive"|"i")
        interactive_task_selection
        ;;
    
    "tasks"|"t")
        print_task_list
        ;;
    
    "vivaria-status"|"vs")
        check_vivaria_services_status
        ;;
    
    "restart-vivaria"|"restart-services")
        restart_vivaria_services
        ;;
    
    "stop-vivaria"|"stop-services")
        stop_vivaria_services
        ;;
    
    "start-vivaria"|"start-services")
        start_vivaria_services
        ;;
    
    "help"|"--help"|"-h")
        show_help
        ;;
    
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        show_help
        exit 1
        ;;
esac
