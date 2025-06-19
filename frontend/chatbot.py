import streamlit as st
import httpx
from typing import Dict, Any

class Chatbot:
    def __init__(self, api_url: str):
        self.api_url = api_url
        if "messages" not in st.session_state:
            st.session_state.messages = []
        # Flag to track if the backend needs to be called
        if "run_backend" not in st.session_state:
            st.session_state.run_backend = False

        self.tool_friendly_names = {
            "ner_generator_dynamic": "NER Generator Agent",
            "create_sql": "SQL Creation Agent",
            "validator_sql_agent": "SQL Validator Agent",
            "run_sqlite_query": "Database Query Agent",
            "handle_error_agent": "Error Handler Agent",
            "generate_final_answer": "Final Answer Agent"
        }
        
        self.agent_explanations = {
            "NER Generator Agent": "Analyzes the user's question to identify key entities like tables and columns.",
            "SQL Creation Agent": "Writes a complex SQL query based on the user's question and the extracted entities.",
            "SQL Validator Agent": "Checks the generated SQL for errors, correcting table/column names against the database schema.",
            "Database Query Agent": "Executes the final, validated SQL query against the database to fetch the data.",
            "Error Handler Agent": "If a query fails, this agent attempts to fix it based on the database error message.",
            "Final Answer Agent": "Formats the data returned from the database into a human-readable final answer."
        }
    
    @st.dialog("About The Agents")
    def show_agent_explanations_dialog(self):
        """Creates the content that will be shown inside the pop-up dialog."""
        for agent_name, description in self.agent_explanations.items():
            st.markdown(f"**{agent_name}:** {description}")

    def display_history(self, chat_container, tool_container):
        """Displays the entire message history from the session state."""
        for message in st.session_state.messages:
            self.display_message(message, chat_container, tool_container)

    def display_message(self, message: Dict, chat_container, tool_container):
        """Displays a single message in the correct column with the correct alignment."""
        role = message.get("role")
        content = message.get("content")

        with chat_container:
            if role == "user" and isinstance(content, str):
                _, col2 = st.columns([1, 4])
                with col2:
                    with st.chat_message("user"):
                        st.markdown(content)

            elif role == "assistant" and isinstance(content, list):
                # This logic is for the right-hand "Agent Steps" panel
                has_tool_calls = any(block.get("type") == "tool_use" for block in content)
                tool_use_blocks = [block for block in content if block.get("type") == "tool_use"]
                
                if tool_use_blocks:
                    with tool_container:
                        for block in tool_use_blocks:
                            technical_name = block.get('name', 'unknown_tool')
                            friendly_name = self.tool_friendly_names.get(technical_name, technical_name)
                            st.info(f"**Tool Used:** {friendly_name}")
                            st.json(block.get('input', {}), expanded=False)
                
                # This logic is for the left-hand "Chat Conversation" panel
                if not has_tool_calls:
                    final_text_blocks = [block for block in content if block.get("type") == "text" and block.get("text")]
                    if final_text_blocks:
                        col1, _ = st.columns([4, 1])
                        with col1:
                            with st.chat_message("assistant"):
                                for block in final_text_blocks:
                                    st.markdown(block.get("text"))

    async def render(self):
        """Sets up the UI and handles the main application logic."""
        st.set_page_config(layout="wide", page_title="MCP SQL Agent")

        st.markdown("""
            <style>
            .title-container { background-color: #f0f2f6; padding: 1rem; border-radius: 0.5rem; text-align: center; margin-bottom: 2rem; }
            .title-container h1 { color: #262730; margin: 0; }
            </style>
            <div class="title-container"><h1>MCP SQL Agent 🤖</h1></div>
        """, unsafe_allow_html=True)

        left_col, right_col = st.columns([2, 1])

        with left_col:
            st.header("Chat Conversation")
            chat_container = st.container(height=600, border=True)
            
        with right_col:
            header_col, button_col = st.columns([0.7, 0.3])
            with header_col:
                st.header("Agent's Internal Steps")
            with button_col:
                st.button("About Agents", on_click=self.show_agent_explanations_dialog)
            
            tool_container = st.container(height=600, border=True)

        if 'show_info' in st.session_state and st.session_state.show_info:
            self.show_agent_explanations_dialog()

        # Always display the full, persistent history
        self.display_history(chat_container, tool_container)
        
        # Handle user input
        if query := st.chat_input("Ask a question about the vehicle data..."):
            st.session_state.messages.append({"role": "user", "content": query})
            st.session_state.run_backend = True
            st.rerun()

        # Call the backend if the flag is set
        if st.session_state.get('run_backend', False):
            st.session_state.run_backend = False
            query = st.session_state.messages[-1]['content']
            with st.spinner("Agent is thinking..."):
                try:
                    async with httpx.AsyncClient(timeout=300.0) as client:
                        response = await client.post(f"{self.api_url}/query", json={"query": query})
                        response.raise_for_status()
                        data = response.json()
                        
                        # --- THE FIX: Append new messages instead of overwriting history ---
                        # The backend returns a history for the current query, starting with the user's question.
                        # We get only the new messages from the assistant by slicing the list.
                        new_assistant_messages = data["messages"][1:]
                        
                        # Add these new messages to our persistent conversation history
                        st.session_state.messages.extend(new_assistant_messages)
                        
                        # Rerun to display the updated, full history
                        st.rerun()

                except Exception as e:
                    st.error(f"An error occurred: {str(e)}")
                    # On error, we remove the user's last question to prevent a broken state
                    st.session_state.messages.pop()