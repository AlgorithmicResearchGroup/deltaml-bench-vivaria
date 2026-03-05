#!/usr/bin/env python3
"""
Simple return function that generated code can use to submit answers.
This avoids complex imports and async issues.
"""

def submit_answer(predictions, score, submission_path='submission.txt', score_path='score.txt'):
    """
    Submit answer in the expected format.
    
    Args:
        predictions: List or array of predictions
        score: Achieved score/accuracy
        submission_path: Path to save predictions (default: submission.txt)
        score_path: Path to save score (default: score.txt)
    """
    # Save predictions
    with open(submission_path, 'w') as f:
        if isinstance(predictions, (list, tuple)):
            f.write('\n'.join(map(str, predictions)))
        else:
            f.write(str(predictions))
    
    # Save score
    with open(score_path, 'w') as f:
        f.write(str(score))
    
    # Signal completion
    print(f"TASK_COMPLETE: submission_path={submission_path} score={score}")
    
    return {
        'status': 'success',
        'submission_path': submission_path,
        'score_path': score_path,
        'score': score
    }

# Make it available as a direct call
if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 3:
        # Can be called from command line
        # Usage: python simple_return.py "1,2,3,4,5" 0.95
        predictions = sys.argv[1].split(',')
        score = float(sys.argv[2])
        submit_answer(predictions, score)
