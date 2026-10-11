import logging
import os

import uvicorn

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "app.server:app",
        host="127.0.0.1",
        port=12362,
        reload=os.environ.get("OKAERI_RELOAD") == "1",
        workers=1,
    )
