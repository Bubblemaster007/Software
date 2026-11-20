"""Only the registered study queue can select an implementation."""
import sys
from backend.study_jobs import execute

if __name__ == '__main__':
    execute(sys.argv[1], sys.argv[2])
