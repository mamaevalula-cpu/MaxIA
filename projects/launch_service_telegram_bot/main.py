import logging
import os
from dotenv import load_dotenv

# Load config from .env
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main() -> None:
    """Main entry point for the launch_service_telegram_bot."""
    try:
        # TODO: Initialize Telegram bot API
        # TODO: Integrate with SaaS-API
        # TODO: Implement business logic for direct offers
        logger.info("Bot is running...")
        # Keep the bot running indefinitely
        while True:
            pass
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error(f"An error occurred: {e}")

if __name__ == '__main__':
    main()