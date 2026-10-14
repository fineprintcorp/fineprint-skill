# Glama-verified Dockerfile for the Fineprint MCP server.
# Runs the server over stdio (default FastMCP transport).
# No API key required at startup — tools fail gracefully at call time
# without one, but MCP introspection (initialize + tools/list) works keyless.
FROM python:3.12-slim

# Required by the official MCP Registry: binds this image to the server name.
LABEL io.modelcontextprotocol.server.name="io.github.fineprintcorp/fineprint"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_server.py legal.py ./

# Stdio transport: Glama pipes JSON-RPC over stdin/stdout.
CMD ["python", "mcp_server.py"]
