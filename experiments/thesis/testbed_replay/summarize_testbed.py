"""Thin wrapper around `testbed/summarize_testbed.py` summarizing the current directory."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "testbed")))
from summarize_testbed import summarize_dir  # noqa: E402


if __name__ == "__main__":
    print(summarize_dir(HERE, HERE), end="")
