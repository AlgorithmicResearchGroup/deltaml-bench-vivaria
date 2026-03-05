# Peptides-struct GCN+ Task

## Overview

This task focuses on improving the GCN+ model on the Peptides-struct dataset.

## Task Description

**Objective**: Improve the GCN+ model to achieve better performance on the Peptides-struct dataset.

**Paper**: Unlocking the Potential of Classic GNNs for Graph-level Tasks: Simple Architectures Meet Excellence

## Baseline Performance

The current GCN+ model achieves:
- **MAE**: 0.2421 ± 0.0016

## Evaluation Metrics

The task is evaluated based on MAE improvement over baseline.

## How to Run

### Using Vivaria Manager Script
```bash
# Navigate to the project root
cd /path/to/Coding-Agent-For-REBench

# Run the task using the manager script
./run_tasks.sh start pwc_peptides_struct_gcn
```



## Training Time

| Training Time |
|---------------|
| 9 hours |

## Resources Provided

- **Research Paper**: Original paper with detailed methodology
- **Source Code**: Complete implementation of the GCN+ model
- **Dataset**: Peptides-struct dataset (if provided)
- **Solution Template**: Starting point for implementation

## File Structure

```
peptides_struct_gcn/
├── peptides_struct_gcn.py           # Main task definition
├── manifest.yaml            # Task configuration
├── build_steps.json         # Environment setup
├── requirements.txt         # Dependencies
├── README.md               # This file
└── assets/
    ├── score.py            # Scoring logic
    └── for_agent/
        ├── paper.pdf       # Research paper
        ├── repo.zip        # Source code
        ├── dataset.zip     # Dataset (if provided)
        └── solution.py     # Implementation template
```

## Implementation Guidelines

1. Study the baseline implementation
2. Analyze the dataset and task requirements
3. Identify improvement opportunities
4. Implement and validate changes
5. Ensure reproducible results

## Validation

Implement your solution with the expected interface:

```python
def evaluate() -> Dict[str, float]:
    # Your implementation here
    return {
        'mae': your_score
    }
```