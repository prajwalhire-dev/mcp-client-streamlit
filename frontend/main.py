import asyncio
from chatbot import Chatbot

async def run_app():
    """Initializes and renders the chatbot application."""
    api_url = "http://localhost:8000"
    chatbot = Chatbot(api_url)
    await chatbot.render()

if __name__ == "__main__":
    # Runs the asynchronous application
    asyncio.run(run_app())