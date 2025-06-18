import streamlit as st
import httpx
from typing import Dict, Any, List
import json

class Chatbot:
    def __init__(self, api_url: str):
        self.api_url = api_url
        if "messages" not in st.session_state:
            st.session_state["messages"] = []

    def display_message(self, message: Dict[str, Any]):
        role = message["role"]
        
        # Skip displaying tool results as a separate message
        if role == "user" and isinstance(message["content"], list) and message["content"][0].get("type") == "tool_result":
             return

        with st.chat_message(role):
            if isinstance(message["content"], str):
                st.markdown(message["content"])
            elif isinstance(message["content"], list):
                for content_block in message["content"]:
                    if content_block["type"] == "text":
                        st.markdown(content_block["text"])
                    elif content_block["type"] == "tool_use":
                        st.write(f"Calling tool: `{content_block['name']}`")
                        st.json(content_block['input'], expanded=False)

    async def render(self):
        st.title("MCP SQL Agent Chat")

        # Display existing messages
        for message in st.session_state.messages:
            self.display_message(message)

        # Handle new query
        if query := st.chat_input("Ask a question about the vehicle data..."):
            st.session_state.messages.append({"role": "user", "content": query})
            self.display_message({"role": "user", "content": query})

            with st.spinner("Thinking..."):
                async with httpx.AsyncClient(timeout=300.0) as client:
                    try:
                        response = await client.post(
                            f"{self.api_url}/query",
                            json={"query": query},
                        )
                        response.raise_for_status() # Raise an exception for bad status codes
                        
                        data = response.json()
                        st.session_state["messages"] = data["messages"]
                        
                        # Clear the chat and re-render all messages from the history
                        st.rerun()

                    except httpx.RequestError as e:
                        st.error(f"Network error: Could not connect to the backend at {self.api_url}. Is it running?")
                        st.session_state.messages.pop() # Remove the user's message on error
                    except httpx.HTTPStatusError as e:
                        st.error(f"Error from backend: {e.response.status_code} - {e.response.text}")
                        st.session_state.messages.pop()
                    except Exception as e:
                        st.error(f"An unexpected error occurred: {str(e)}")
                        st.session_state.messages.pop()