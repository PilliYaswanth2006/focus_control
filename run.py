import os
from app import create_app


app = create_app()


if __name__ == "__main__":
    host = os.environ.get("FOCUS_CONTROL_HOST", "127.0.0.1")
    port = int(os.environ.get("FOCUS_CONTROL_PORT", "5000"))
    debug = os.environ.get("FOCUS_CONTROL_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
