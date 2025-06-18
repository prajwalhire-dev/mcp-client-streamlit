from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any
from contextlib import asynccontextmanager
from mcp_client import MCPClient
from dotenv import load_dotenv

# Load environment variables from .env file at the very beginning
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Backend starting up...")
    client = MCPClient()
    try:
        # We assume server.py is in the same directory
        await client.connect_to_server("server.py")
        app.state.client = client
        print("Backend startup complete. MCP Client connected.")
        yield
    finally:
        # Shutdown
        print("Backend shutting down...")
        await client.cleanup()
        print("Backend shutdown complete.")

app = FastAPI(title="MCP SQL Agent API", lifespan=lifespan)

# Allow all origins for simplicity, but you can restrict this in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class QueryRequest(BaseModel):
    query: str

@app.post("/query")
async def process_query(request: QueryRequest) -> Dict[str, List[Dict[str, Any]]]:
    """Processes a query through the MCP agent and returns the conversation history."""
    client: MCPClient = app.state.client
    try:
        messages = await client.process_query(request.query)
        return {"messages": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)