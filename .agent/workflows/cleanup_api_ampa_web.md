---
description: Cleanup Api_AMPA_WEB.py
---
# Cleanup Api_AMPA_WEB.py

The goal is to reduce the size of `Api_AMPA_WEB.py` by removing code that has been moved to the `app/` directory and `config.py`.

## Steps
1.  Verify that all components in `Api_AMPA_WEB.py` are present in `app/`, `config.py`, or `app.py`. (Done)
2.  Replace the content of `Api_AMPA_WEB.py` with a minimal entry point that imports `create_app` from `app` and runs it.
3.  Verify that the application still starts (I cannot run it, but I can check for syntax errors or missing imports).
