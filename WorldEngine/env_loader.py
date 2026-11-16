"""
Environment configuration loader for MACSWC.

Loads environment variables from .env file if python-dotenv is available.
Falls back to system environment variables if not.
"""

import os
from pathlib import Path


def load_env() -> None:
    """
    Loads environment variables from .env file in project root.
    Gracefully falls back to system environment if dotenv not available.
    """
    try:
        from dotenv import load_dotenv
        
        # Find .env file in project root
        project_root = Path(__file__).resolve().parent.parent
        env_file = project_root / ".env"
        
        if env_file.exists():
            load_dotenv(dotenv_path=env_file, override=True)
            print(f"✓ Configuration loaded from: {env_file}")
            
            # Display current configuration
            display_mode = os.getenv("DISPLAY_MODE", "short")
            gui_enabled = os.getenv("GUI_ENABLED", "0")
            backend = os.getenv("COUNTRY_AGENT_BACKEND", "hf_api")
            
            print(f"  - Display Mode: {display_mode}")
            print(f"  - GUI: {'enabled' if gui_enabled == '1' else 'disabled'}")
            print(f"  - Country Agent Backend: {backend}")
        else:
            print(f"ℹ  No .env file found at {env_file}")
            print("  Using system environment variables or defaults")
            
    except ImportError:
        print("ℹ  python-dotenv not installed")
        print("  Using system environment variables")
        print("  Install with: pip install python-dotenv")


def get_env(key: str, default: str = "") -> str:
    """
    Get environment variable with fallback to default.
    
    Args:
        key: Environment variable name
        default: Default value if not set
        
    Returns:
        Environment variable value or default
    """
    return os.getenv(key, default).strip()
