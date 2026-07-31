"""Run with: python main.py
Then open http://localhost:8056 in a browser."""

import uvicorn
from chartwatch import config as cfg_module

if __name__ == "__main__":
    cfg = cfg_module.load()
    uvicorn.run(
        "chartwatch.api:app",
        host=cfg["server"]["host"],
        port=cfg["server"]["port"],
        reload=False,
    )
