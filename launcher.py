"""Entry point of the built app (Budget.app on a Mac, Budget.exe on Windows).

    Budget --smoke-test   start against a temporary data folder, check that the
                          page and API answer, then exit (0 = OK). Used by CI.
"""
import os
import sys
import tempfile

if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        os.environ["BUDGET_DATA_DIR"] = tempfile.mkdtemp(prefix="budget-smoke-")
        from app.desktop import smoke_test
        sys.exit(smoke_test())
    from app.desktop import main
    main()
