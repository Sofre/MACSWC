"""
Quick test script to verify API keys are working.
Tests OpenAI and Groq API endpoints for Secretary and Board agents.
"""
import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from dotenv import load_dotenv

# Load .env file if it exists
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
    print(f"✓ Loaded environment from: {env_path}\n")

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

def test_api_key(api_key: str, key_name: str, provider: str = "openai", model: str = "gpt-4o-mini") -> bool:
    """Test if an API key works by making a minimal API call."""
    if not api_key:
        print(f"❌ {key_name}: NOT SET (no API key found)")
        return False
    
    # Show masked API key
    masked_key = api_key[:7] + "..." + api_key[-4:] if len(api_key) > 11 else "***"
    print(f"Testing {key_name} ({provider.upper()}): {masked_key}")
    
    # Select API URL based on provider
    api_url = GROQ_CHAT_URL if provider == "groq" else OPENAI_CHAT_URL
    
    # Make minimal test call
    payload = {
        "model": model,
        "temperature": 0.0,
        "max_tokens": 10,
        "messages": [
            {"role": "user", "content": "Say 'OK' if you can hear me."}
        ],
    }
    
    try:
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            api_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "MACSWC/1.0 (Python)",
            },
            method="POST",
        )
        
        with urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            result = json.loads(body)
            
            # Check if we got a valid response
            if "choices" in result and len(result["choices"]) > 0:
                message = result["choices"][0].get("message", {}).get("content", "")
                print(f"✓ {key_name}: WORKING - Response: '{message}'")
                
                # Show usage info if available
                if "usage" in result:
                    usage = result["usage"]
                    print(f"  Tokens used: {usage.get('total_tokens', 'N/A')}")
                
                return True
            else:
                print(f"⚠ {key_name}: Unexpected response format")
                print(f"  Response: {body[:200]}")
                return False
                
    except HTTPError as e:
        error_body = e.read().decode("utf-8") if hasattr(e, 'read') else str(e)
        print(f"❌ {key_name}: HTTP ERROR")
        print(f"  Status: {e.code}")
        print(f"  Error: {error_body[:300]}")
        
        # Check for common error codes
        if e.code == 401:
            print(f"  → Invalid API key or authentication failed")
        elif e.code == 429:
            print(f"  → Rate limit exceeded or quota exhausted")
            print(f"  → Check your OpenAI billing dashboard: https://platform.openai.com/usage")
        elif e.code == 403:
            print(f"  → Forbidden - API key may not have access to this model")
        
        return False
        
    except URLError as e:
        print(f"❌ {key_name}: NETWORK ERROR")
        print(f"  Error: {e.reason}")
        return False
        
    except Exception as e:
        print(f"❌ {key_name}: UNEXPECTED ERROR")
        print(f"  Error: {type(e).__name__}: {e}")
        return False
    
    finally:
        print()


def main():
    print("="*70)
    print("  MACSWC API KEY TEST")
    print("="*70)
    print()
    
    # Get API keys from environment
    openai_key = os.getenv("OPENAI_API_KEY")
    board_key = os.getenv("BOARD_AGENT_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    
    # Get provider settings
    secretary_provider = os.getenv("SECRETARY_AGENT_PROVIDER", "groq").lower()
    board_provider = os.getenv("BOARD_AGENT_PROVIDER", "groq").lower()
    
    results = []
    
    # Test Groq API Key (if configured)
    if secretary_provider == "groq" or board_provider == "groq":
        print("1. Testing Groq API Key (Primary)")
        print("-" * 70)
        if groq_key:
            groq_ok = test_api_key(groq_key, "GROQ_API_KEY", "groq", "llama-3.3-70b-versatile")
            results.append(("Groq", groq_ok))
        else:
            print("❌ GROQ_API_KEY: NOT SET")
            print("   Get your free API key at: https://console.groq.com/")
            results.append(("Groq", False))
        print()
    
    # Test OpenAI API Key (if configured or as fallback)
    if secretary_provider == "openai" or board_provider == "openai" or not groq_key:
        print("2. Testing OpenAI API Key")
        print("-" * 70)
        if openai_key:
            openai_ok = test_api_key(openai_key, "OPENAI_API_KEY", "openai", "gpt-4o-mini")
            results.append(("OpenAI", openai_ok))
        else:
            print("❌ OPENAI_API_KEY: NOT SET")
            results.append(("OpenAI", False))
        print()
    
    # Summary
    print("="*70)
    print("  SUMMARY")
    print("="*70)
    
    working_providers = [name for name, ok in results if ok]
    
    if working_providers:
        print(f"✓ Working providers: {', '.join(working_providers)}")
        print("\nSecretary and Board agents should function correctly.")
    elif results:
        print("❌ No API keys are working!")
        print("\nSecretary and Board agents will use fallback behavior.")
        print("Decisions will still be made by Country Agents, but without")
        print("Secretary validation and Board evaluation.")
    
    print("\nAgent Configuration:")
    print(f"  - SECRETARY_AGENT_ENABLED: {os.getenv('SECRETARY_AGENT_ENABLED', '0')}")
    print(f"  - SECRETARY_AGENT_PROVIDER: {secretary_provider}")
    print(f"  - BOARD_AGENT_ENABLED: {os.getenv('BOARD_AGENT_ENABLED', '1')}")
    print(f"  - BOARD_AGENT_PROVIDER: {board_provider}")
    print(f"  - BOARD_AGENT_LLM_ENABLED: {os.getenv('BOARD_AGENT_LLM_ENABLED', '0')}")
    
    if not working_providers:
        print("\nTo get started with Groq (FREE):")
        print("  1. Sign up at: https://console.groq.com/")
        print("  2. Create an API key")
        print("  3. Add to .env: GROQ_API_KEY=your_key_here")
        print("  4. Enjoy 14,400 free requests per day!")
    print()


if __name__ == "__main__":
    main()
