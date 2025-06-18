import streamlit as st
import httpx
from typing import Dict, Any

class Chatbot:
    def __init__(self, api_url: str):
        self.api_url = api_url
        # Initialize session state for messages if it doesn't exist
        if "messages" not in st.session_state:
            st.session_state.messages = []

    def display_history(self, chat_container, tool_container):
        """
        Displays the conversation and tool calls from session state into their respective containers,
        applying the new filtering logic for the chat.
        """
        for message in st.session_state.messages:
            role = message.get("role")
            content = message.get("content")

            if role == "user" and isinstance(content, str):
                # Display user messages in the left column's chat container
                with chat_container:
                    with st.chat_message("user"):
                        st.markdown(content)

            elif role == "assistant" and isinstance(content, list):
                # --- NEW LOGIC: Differentiate final answers from thinking steps ---
                
                # A message is a "thinking step" if it contains tool calls.
                has_tool_calls = any(block.get("type") == "tool_use" for block in content)
                
                # A message is a "final answer" if it has text AND NO tool calls.
                if not has_tool_calls:
                    final_text_blocks = [block for block in content if block.get("type") == "text" and block.get("text")]
                    if final_text_blocks:
                        with chat_container:
                            with st.chat_message("assistant"):
                                for block in final_text_blocks:
                                    st.markdown(block.get("text"))
                
                # --- Display tool calls in the right panel regardless ---
                tool_use_blocks = [block for block in content if block.get("type") == "tool_use"]
                if tool_use_blocks:
                    with tool_container:
                        for block in tool_use_blocks:
                            st.info(f"**Tool Used:** `{block.get('name')}`")
                            st.json(block.get('input', {}), expanded=False)


    async def render(self):
        """
        Sets up the UI and handles the main application logic.
        """
        st.set_page_config(layout="wide", page_title="MCP SQL Agent")

        # --- CHANGE 1: Styled and Centered Title ---
        st.markdown("""
            <style>
            .title-container {
                background-color: #f0f2f6;
                padding: 1rem;
                border-radius: 0.5rem;
                text-align: center;
                margin-bottom: 2rem;
            }
            .title-container h1 {
                color: #262730;
                margin: 0;
            }
            </style>
            <div class="title-container">
                <h1>MCP SQL Agent 🤖</h1>
            </div>
        """, unsafe_allow_html=True)

        # 1. Create the two-column layout
        left_col, right_col = st.columns([2, 1])

        # 2. Define containers for each column to hold content
        with left_col:
            st.header("Chat Conversation")
            chat_container = st.container(height=600, border=True)

        with right_col:
            st.header("Agent's Internal Steps")
            tool_container = st.container(height=600, border=True)

        # 3. Display the existing (and now filtered) chat and tool history
        self.display_history(chat_container, tool_container)

        # 4. Handle new user input using the chat_input widget at the bottom of the page
        if query := st.chat_input("Ask a question about the vehicle data..."):
            # Add user message to history and immediately display it
            st.session_state.messages.append({"role": "user", "content": query})
            with chat_container:
                with st.chat_message("user"):
                    st.markdown(query)
            
            # Show a spinner while waiting for the backend
            with st.spinner("Agent is thinking..."):
                async with httpx.AsyncClient(timeout=300.0) as client:
                    try:
                        # Call the backend API
                        response = await client.post(f"{self.api_url}/query", json={"query": query})
                        response.raise_for_status()
                        data = response.json()
                        
                        # Replace local history with the complete history from the backend
                        st.session_state.messages = data["messages"]
                        
                        # Rerun the script to display the new response in the correct containers
                        st.rerun()

                    except Exception as e:
                        st.error(f"An error occurred: {str(e)}")
                        # If an error occurs, remove the last user message to avoid confusion
                        st.session_state.messages.pop()