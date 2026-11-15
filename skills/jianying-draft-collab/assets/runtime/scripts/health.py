"""Compatibility entry point for the unified read-only environment doctor."""
from runtime_env import main
import sys
if __name__=='__main__':
    sys.argv=[sys.argv[0],'doctor',*sys.argv[1:]]
    main()
