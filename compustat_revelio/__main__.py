"""Allow running the pipeline with ``python -m compustat_revelio``."""

from .build_database import main

if __name__ == "__main__":
    main()
