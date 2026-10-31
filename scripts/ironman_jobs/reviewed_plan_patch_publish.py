"""Permanent guarded publisher for separately approved reviewed manifests.

Never use this to retry operations explicitly denied by platform security checks.
"""
from reviewed_plan_patch_pipeline import run_main

if __name__ == "__main__":
    run_main(execute=True)
