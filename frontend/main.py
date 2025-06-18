import asyncio
import streamlit as st
from chatbot import Chatbot

# Configuration
API_URL = "http://localhost:8000"

async def main():
    st.set_page_config(page_title="MCP SQL Agent", page_icon="🤖")
    chatbot = Chatbot(API_URL)
    await chatbot.render()

if __name__ == "__main__":
    asyncio.run(main())