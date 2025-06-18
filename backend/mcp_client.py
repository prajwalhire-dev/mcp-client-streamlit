import asyncio
from typing import Optional, List, Dict, Any
from contextlib import AsyncExitStack
import traceback
import json
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from anthropic import Anthropic, AsyncAnthropic
from anthropic.types import Message

class MCPClient:
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.llm = AsyncAnthropic()
        self.tools: List[Dict[str, Any]] = []
        self.messages: List[Dict[str, Any]] = []

    async def connect_to_server(self, server_script_path: str):
        try:
            print(f"Attempting to connect to MCP server script: {server_script_path}")
            server_params = StdioServerParameters(
                command="python", args=[server_script_path], env=os.environ
            )
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            self.stdio, self.write = stdio_transport
            self.session = await self.exit_stack.enter_async_context(
                ClientSession(self.stdio, self.write)
            )
            await self.session.initialize()
            mcp_tools = await self.session.list_tools()
            self.tools = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                }
                for tool in mcp_tools.tools
            ]
            print(f"Successfully connected to server. Available tools: {[tool['name'] for tool in self.tools]}")
            return True
        except Exception as e:
            print(f"Failed to connect to server: {str(e)}")
            print(f"Connection error details: {traceback.format_exc()}")
            raise

    async def process_query(self, query: str) -> List[Dict[str, Any]]:
        self.messages = [{"role": "user", "content": query}]

        while True:
            print(f"Calling LLM with {len(self.messages)} messages...")
            response: Message = await self.llm.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4096,
                messages=self.messages,
                tools=self.tools,
            )

            response_message = response.content
            has_tool_call = any(block.type == "tool_use" for block in response_message)

            self.messages.append(
                {"role": "assistant", "content": response.content}
            )

            if not has_tool_call:
                print("LLM responded with final answer.")
                break

            print("LLM requested tool calls.")
            tool_results = []
            for content_block in response_message:
                if content_block.type == "tool_use":
                    tool_name = content_block.name
                    tool_input = content_block.input
                    tool_use_id = content_block.id

                    print(f"Executing tool: {tool_name} with args: {tool_input}")
                    try:
                        # The tools in your server.py return JSON strings, so we parse them.
                        # The tool call itself expects a dictionary.
                        tool_input_parsed = {k: json.loads(v) if isinstance(v, str) and v.startswith('{') else v for k, v in tool_input.items()}
                        result = await self.session.call_tool(tool_name, tool_input_parsed)
                        
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": result.content,
                            }
                        )
                    except Exception as e:
                        print(f"Error calling tool {tool_name}: {e}")
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": [{"type": "text", "text": f"Error executing tool: {e}"}],
                                "is_error": True,
                            }
                        )
            
            self.messages.append({"role": "user", "content": tool_results})

        # Convert the complex message objects to a serializable format for the API response
        serializable_messages = []
        for msg in self.messages:
            if isinstance(msg['content'], list):
                content_list = []
                for item in msg['content']:
                    if hasattr(item, 'dict'):
                        content_list.append(item.dict())
                    else:
                        content_list.append(item)
                serializable_messages.append({'role': msg['role'], 'content': content_list})
            else:
                serializable_messages.append(msg)
        
        return serializable_messages

    async def cleanup(self):
        print("Cleaning up resources...")
        await self.exit_stack.aclose()