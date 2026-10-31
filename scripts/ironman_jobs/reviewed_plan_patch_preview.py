"""Permanent read-only publisher preview. No TrainingPeaks mutation."""
from reviewed_plan_patch_pipeline import run_main

if __name__ == "__main__":
    run_main(execute=False)
