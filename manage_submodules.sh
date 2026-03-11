#!/bin/bash

# Git Submodule Manager Script
# Manages git submodules for individual modules or all modules in the repository
# Author: Josias Moukpe <erud1t3.devs@gmail.com>

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Helper functions
print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1" >&2
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_header() {
    echo -e "\n${BLUE}=== $1 ===${NC}"
}

# Get list of submodules
get_submodules() {
    git submodule status | awk '{print $2}' 2>/dev/null || echo ""
}

# Check if submodule exists
submodule_exists() {
    local submodule="$1"
    get_submodules | grep -q "^${submodule}$"
}

# Validate submodule argument
validate_submodule() {
    local submodule="$1"
    if [[ -z "$submodule" ]]; then
        print_error "Submodule name is required"
        return 1
    fi
    
    if ! submodule_exists "$submodule"; then
        print_error "Submodule '$submodule' does not exist"
        print_info "Available submodules:"
        get_submodules | sed 's/^/  - /'
        return 1
    fi
}

# Initialize submodules
init_submodule() {
    local submodule="$1"
    
    if [[ "$submodule" == "all" ]]; then
        print_header "Initializing all submodules"
        git submodule init
        print_success "All submodules initialized"
    else
        validate_submodule "$submodule" || return 1
        print_header "Initializing submodule: $submodule"
        git submodule init "$submodule"
        print_success "Submodule '$submodule' initialized"
    fi
}

# Update submodules
update_submodule() {
    local submodule="$1"
    
    if [[ "$submodule" == "all" ]]; then
        print_header "Updating all submodules"
        git submodule update --remote --recursive
        print_success "All submodules updated"
    else
        validate_submodule "$submodule" || return 1
        print_header "Updating submodule: $submodule"
        git submodule update --remote "$submodule"
        print_success "Submodule '$submodule' updated"
    fi
}

# Clone/fetch submodules
clone_submodule() {
    local submodule="$1"
    
    if [[ "$submodule" == "all" ]]; then
        print_header "Cloning all submodules"
        git submodule update --init --recursive
        print_success "All submodules cloned"
    else
        validate_submodule "$submodule" || return 1
        print_header "Cloning submodule: $submodule"
        git submodule update --init "$submodule"
        print_success "Submodule '$submodule' cloned"
    fi
}

# Check status of submodules
status_submodule() {
    local submodule="$1"
    
    if [[ "$submodule" == "all" ]]; then
        print_header "Status of all submodules"
        git submodule status
    else
        validate_submodule "$submodule" || return 1
        print_header "Status of submodule: $submodule"
        git submodule status "$submodule"
    fi
}

# Reset submodules to committed state
reset_submodule() {
    local submodule="$1"
    
    if [[ "$submodule" == "all" ]]; then
        print_header "Resetting all submodules"
        git submodule foreach --recursive 'git reset --hard HEAD && git clean -fd'
        print_success "All submodules reset"
    else
        validate_submodule "$submodule" || return 1
        print_header "Resetting submodule: $submodule"
        cd "$submodule"
        git reset --hard HEAD
        git clean -fd
        cd - > /dev/null
        print_success "Submodule '$submodule' reset"
    fi
}

# Sync submodules URLs
sync_submodule() {
    local submodule="$1"
    
    if [[ "$submodule" == "all" ]]; then
        print_header "Syncing all submodules"
        git submodule sync --recursive
        print_success "All submodules synced"
    else
        validate_submodule "$submodule" || return 1
        print_header "Syncing submodule: $submodule"
        git submodule sync "$submodule"
        print_success "Submodule '$submodule' synced"
    fi
}

# List submodules
list_submodules() {
    print_header "Available submodules"
    local submodules=$(get_submodules)
    
    if [[ -z "$submodules" ]]; then
        print_warning "No submodules found in this repository"
        return 0
    fi
    
    echo "$submodules" | while read -r submodule; do
        if [[ -e "$submodule/.git" ]]; then
            local status="✓ Initialized"
            local color="$GREEN"
        else
            local status="✗ Not initialized"
            local color="$RED"
        fi
        echo -e "  - ${color}$submodule${NC} ($status)"
    done
}

# Detailed info about submodules
info_submodule() {
    local submodule="$1"
    
    if [[ "$submodule" == "all" ]]; then
        print_header "Detailed info for all submodules"
        get_submodules | while read -r sm; do
            echo -e "\n${BLUE}Submodule: $sm${NC}"
            git submodule status "$sm"
            local url=$(git config --file .gitmodules submodule."$sm".url)
            echo "  URL: $url"
            if [[ -e "$sm/.git" ]]; then
                local branch=$(cd "$sm" && git branch --show-current 2>/dev/null || echo "detached")
                local commit=$(cd "$sm" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
                echo "  Branch: $branch"
                echo "  Commit: $commit"
            fi
        done
    else
        validate_submodule "$submodule" || return 1
        print_header "Detailed info for submodule: $submodule"
        git submodule status "$submodule"
        local url=$(git config --file .gitmodules submodule."$submodule".url)
        echo "URL: $url"
        if [[ -e "$submodule/.git" ]]; then
            local branch=$(cd "$submodule" && git branch --show-current 2>/dev/null || echo "detached")
            local commit=$(cd "$submodule" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
            echo "Branch: $branch"
            echo "Commit: $commit"
        fi
    fi
}

# Pull latest changes for submodules
pull_submodule() {
    local submodule="$1"
    
    if [[ "$submodule" == "all" ]]; then
        print_header "Pulling latest changes for all submodules"
        git submodule foreach --recursive 'git pull origin $(git branch --show-current || echo main)'
        print_success "All submodules pulled"
    else
        validate_submodule "$submodule" || return 1
        if [[ ! -e "$submodule/.git" ]]; then
            print_error "Submodule '$submodule' is not initialized. Run 'clone' first."
            return 1
        fi
        
        print_header "Pulling latest changes for submodule: $submodule"
        cd "$submodule"
        local branch=$(git branch --show-current || echo main)
        git pull origin "$branch"
        cd - > /dev/null
        print_success "Submodule '$submodule' pulled"
    fi
}

# Show help
show_help() {
    cat << EOF
Git Submodule Manager

USAGE:
    $0 <command> [submodule|all]

COMMANDS:
    init <submodule|all>     Initialize submodule(s)
    update <submodule|all>   Update submodule(s) to latest remote
    clone <submodule|all>    Clone/fetch submodule(s) 
    status <submodule|all>   Show status of submodule(s)
    reset <submodule|all>    Reset submodule(s) to committed state
    sync <submodule|all>     Sync submodule(s) URLs
    pull <submodule|all>     Pull latest changes for submodule(s)
    info <submodule|all>     Show detailed info about submodule(s)
    list                     List all available submodules
    help                     Show this help message

EXAMPLES:
    $0 list                  # List all submodules
    $0 clone all             # Clone all submodules
    $0 init deltamlbench     # Initialize deltamlbench submodule
    $0 update all            # Update all submodules
    $0 status vivaria        # Check status of vivaria submodule
    $0 info all              # Show detailed info for all submodules

SUBMODULES:
    Use 'all' to operate on all submodules, or specify individual submodule names.
    Available submodules in this repository:
$(get_submodules | sed 's/^/    - /')

EOF
}

# Main script logic
main() {
    # Change to script directory
    cd "$SCRIPT_DIR"
    
    # Check if we're in a git repository
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        print_error "Not in a git repository"
        exit 1
    fi
    
    # Check if there are submodules
    if [[ -z "$(get_submodules)" ]] && [[ "$1" != "help" ]]; then
        print_error "No submodules found in this repository"
        exit 1
    fi
    
    local command="$1"
    local target="$2"
    
    case "$command" in
        init)
            init_submodule "$target"
            ;;
        update)
            update_submodule "$target"
            ;;
        clone)
            clone_submodule "$target"
            ;;
        status)
            status_submodule "$target"
            ;;
        reset)
            reset_submodule "$target"
            ;;
        sync)
            sync_submodule "$target"
            ;;
        pull)
            pull_submodule "$target"
            ;;
        info)
            info_submodule "$target"
            ;;
        list)
            list_submodules
            ;;
        help|--help|-h|"")
            show_help
            ;;
        *)
            print_error "Unknown command: $command"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"
