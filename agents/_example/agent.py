"""Example native agent — reads JSON-RPC from stdin, writes to stdout."""

import json
import sys
import time

START_TIME = time.time()


def handle_request(request: dict) -> dict:
    method = request.get("method", "")
    params = request.get("params", {})
    request_id = request.get("id")

    if method == "initialize":
        result = {"status": "ok"}
    elif method == "execute":
        action = params.get("action", "")
        args = params.get("args", {})
        if action == "say_hello":
            name = args.get("name", "World")
            result = {"message": f"Hello, {name}!"}
        else:
            result = {"error": f"Unknown action: {action}"}
    elif method == "health":
        result = {"status": "healthy", "uptime_s": int(time.time() - START_TIME)}
    elif method == "shutdown":
        result = {"status": "ok"}
        response = {"jsonrpc": "2.0", "result": result, "id": request_id}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
        sys.exit(0)
    else:
        return {
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": f"Method not found: {method}"},
            "id": request_id,
        }

    return {"jsonrpc": "2.0", "result": result, "id": request_id}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
        except json.JSONDecodeError:
            response = {
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": "Parse error"},
                "id": None,
            }
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
