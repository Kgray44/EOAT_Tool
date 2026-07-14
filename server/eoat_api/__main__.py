import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "server.eoat_api.app:app",
        host=os.getenv("EOAT_API_HOST", "127.0.0.1"),
        port=int(os.getenv("EOAT_API_PORT", "8765")),
        reload=False,
    )
