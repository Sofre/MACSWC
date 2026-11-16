# Assets Folder

## Structure

- `balkans_map.png` - Background map of the Balkans region
- `flags/` - Country flag images (circular or square, will be cropped to circles)

## Flag Files

Place flag images here with these names:
- `bulgaria.png`
- `serbia.png`
- `greece.png`
- `romania.png`
- `ottoman_empire.png`
- `montenegro.png`

Recommended size: 64x64 pixels or higher (will be scaled to fit circles)

# GUI Configuration Guide



## Performance Optimization

**The GUI is automatically disabled when local LLM agents are detected.**

### Why?

Running the GUI concurrently with local language models (e.g., Ollama) causes severe performance degradation:
- Local LLM inference is CPU/GPU intensive
- GUI rendering requires additional system resources
- Combined load leads to:
  - Slow agent response times (60+ seconds per decision)
  - Laggy or frozen GUI updates
  - Overall poor user experience

### Automatic Detection

The system checks if all agents are using API endpoints:

```python
def _all_agents_use_api() -> bool:
    """Checks if all agents use API (not local)."""
    country_backend = os.getenv("COUNTRY_AGENT_BACKEND", "hf_api")
    country_enabled = os.getenv("COUNTRY_AGENT_ENABLED", "0")
    
    if country_enabled and country_backend != "hf_api":
        return False  # Local backend detected
    
    return True
```

**GUI is enabled only when:**
1. `GUI_ENABLED='1'`
2. Pygame is available
3. **All agents use API** (`COUNTRY_AGENT_BACKEND='hf_api'`)

## Configuration Examples

### Working Configuration (GUI Enabled)

```powershell
# Use the pre-configured script
. .\engine_tune\mode_run_long_with_gui.ps1

# Or set manually:
$env:GUI_ENABLED='1'
$env:COUNTRY_AGENT_BACKEND='hf_api'  # Required for GUI
$env:COUNTRY_AGENT_ENABLED='1'
$env:HF_TOKEN='your_token_here'
```

### Local Configuration (GUI Auto-Disabled)

```powershell
$env:GUI_ENABLED='1'
$env:COUNTRY_AGENT_BACKEND='ollama'  # Local - GUI will be disabled
$env:COUNTRY_AGENT_OLLAMA_URL='http://localhost:11434/api/chat'
$env:COUNTRY_AGENT_OLLAMA_MODEL='qwen2.5:14b-instruct'
```

**Output:**
```
============================================================
WARNING: GUI is disabled because local agents are being used.
GUI only works when ALL agents use API endpoints to avoid performance issues.
Current configuration:
  - Country Agent Backend: ollama

To enable GUI:
  1. Set COUNTRY_AGENT_BACKEND='hf_api' (not 'ollama')
  2. Ensure all agents have valid API keys
  3. Use one of the API-enabled run scripts (e.g., mode_run_long_with_gui.ps1)
============================================================
```

## Agent Backend Options

### API Backends (GUI Compatible)

| Backend | Environment Variable | Notes |
|---------|---------------------|-------|
| Hugging Face API | `COUNTRY_AGENT_BACKEND='hf_api'` | Fast, cloud-based, GUI compatible |
| OpenAI API (Secretary) | Automatic via `OPENAI_API_KEY` | Always compatible |
| OpenAI API (Board) | Automatic via `BOARD_AGENT_API_KEY` | Always compatible |

### Local Backends (GUI Incompatible)

| Backend | Environment Variable | Notes |
|---------|---------------------|-------|
| Ollama | `COUNTRY_AGENT_BACKEND='ollama'` | Slow, local inference, **GUI disabled** |

## Recommended Scripts

Use these pre-configured scripts for best experience:

### With GUI (Fast, API-based)
- `mode_run_long_with_gui.ps1` - Full display + visual interface
- `mode_run_short_with_gui.ps1` - Summary + visual interface

### Without GUI (Terminal only)
- `mode_run_long_without_gui.ps1` - Detailed logs, no GUI overhead
- `mode_run_short_without_gui.ps1` - Summary, no GUI overhead
- `mode_run_long_debug.ps1` - Debug mode, focus on logs
- `mode_run_short_debug.ps1` - Debug mode, concise output

## Troubleshooting

### GUI doesn't appear

**Check:**
1. Is Pygame installed? `pip install pygame`
2. Is `GUI_ENABLED='1'`?
3. Is `COUNTRY_AGENT_BACKEND='hf_api'`?
4. Do you have valid API tokens?

**Verify:**
```powershell
# Check current configuration
$env:GUI_ENABLED
$env:COUNTRY_AGENT_BACKEND
$env:HF_TOKEN
```

### "GUI disabled because local agents" warning

This is expected behavior when using `COUNTRY_AGENT_BACKEND='ollama'`. 

**To fix:**
- Switch to API backend: `$env:COUNTRY_AGENT_BACKEND='hf_api'`
- Or use a `*_without_gui.ps1` script for local testing

### GUI is slow or laggy

If you're using API backends and still experiencing lag:
- Check your network connection
- Verify API rate limits aren't being hit
- Try using `mode_run_short_with_gui.ps1` for less verbose output

## Implementation Details

The GUI check is performed at three key points:

1. **Initialization** (`run_decision_action_layers`)
   - Checks configuration
   - Shows warning if GUI requested but agents are local
   - Initializes GUI only if all conditions met

2. **Action Display** (`_stream_action`)
   - Updates GUI with each action
   - Only if GUI was successfully initialized

3. **Round Updates** (`decide_round_actions`)
   - Refreshes GUI between country decisions
   - Allows user to close window mid-simulation

All checks use the `_all_agents_use_api()` function to ensure consistency.

## Performance Benchmarks

Approximate decision times per country:

| Configuration | Avg Time | GUI Status |
|---------------|----------|------------|
| HF API + GUI | 3-8s | Enabled, smooth |
| HF API no GUI | 3-8s | Disabled by choice |
| Ollama + GUI | 30-60s+ | Auto-disabled (would be worse) |
| Ollama no GUI | 25-50s | Disabled, acceptable |

**Recommendation:** Use API backends with GUI for the best experience during development and presentations. Use local backends without GUI for cost-effective batch processing or offline testing.
