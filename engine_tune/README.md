# MACSWC Engine Run Scripts

Simple one-click scripts to run the simulation with different configurations.

## Quick Start

Just run the script that matches your needs:

```powershell
.\engine_tune\run_api_gui_long.ps1
```

That's it! The script will:
1. Load the appropriate configuration from .env templates
2. Start the simulation
3. Display results

## Available Scripts

| Script | Display | GUI | Backend | Speed | Cost |
|--------|---------|-----|---------|-------|------|
| `run_api_gui_long.ps1` | Long | Yes | API | Fast | $$ |
| `run_api_gui_short.ps1` | Short | Yes | API | Fast | $$ |
| `run_api_long.ps1` | Long | No | API | Fast | $$ |
| `run_api_short.ps1` | Short | No | API | Fast | $ |
| `run_local_long.ps1` | Long | No | Local | Slow | $ |
| `run_local_short.ps1` | Short | No | Local | Slow | Free |
| `run_local_all_long.ps1` | Long | No | Local | Slow | Free |
| `run_debug_long.ps1` | Long | No | API | Fast | $$ |
| `run_debug_short.ps1` | Short | No | API | Fast | $ |

**Legend:**
- **Display:** Long = detailed logs, Short = summary only
- **GUI:** Pygame visual interface (only works with API backend)
- **Backend:** API = cloud APIs, Local = Ollama (requires local setup)
- **Speed:** Fast = 3-8s per decision, Slow = 25-50s per decision
- **Cost:** $ = minimal, $$ = moderate API usage, Free = no API calls

## How It Works

### .env Configuration System

The scripts use .env template files for configuration:

- `.env.api_gui_long` - API with GUI, long display
- `.env.api_gui_short` - API with GUI, short display
- `.env.api_long` - API without GUI, long display
- `.env.api_short` - API without GUI, short display
- `.env.local_long` - Local Ollama, long display
- `.env.local_short` - Local Ollama, short display
- `.env.local_all_long` - Local Ollama for Country, Secretary, and Board agents; long display
- `.env.debug_long` - Debug mode, long display
- `.env.debug_short` - Debug mode, short display

When you run a script, it copies the appropriate template to `.env` and runs the simulation.

### Manual Configuration

You can also manually configure by copying a template:

```powershell
# Copy the configuration you want
Copy-Item .env.api_gui_long .env

# Run directly
python -m WorldEngine.playground
```

## Script Details

### API with GUI Scripts

**Best for:** Presentations, visual analysis, real-time monitoring

```powershell
.\engine_tune\run_api_gui_long.ps1   # Detailed with visuals
.\engine_tune\run_api_gui_short.ps1  # Summary with visuals
```

Requirements:
- API keys configured in .env template
- Pygame installed
- All agents use API (fast)

### API without GUI Scripts

**Best for:** Production runs, batch processing, headless servers

```powershell
.\engine_tune\run_api_long.ps1   # Detailed logs
.\engine_tune\run_api_short.ps1  # Summary only
```

Requirements:
- API keys configured in .env template
- Faster execution (no GUI overhead)

### Local Scripts

**Best for:** Cost savings, offline testing, development

```powershell
.\engine_tune\run_local_long.ps1   # Detailed with local agent
.\engine_tune\run_local_short.ps1  # Summary with local agent
.\engine_tune\run_local_all_long.ps1  # Detailed with all agents local
```

Requirements:
- Ollama installed and running locally
- Model `qwen2.5:14b-instruct` downloaded
- Slower but free Country Agent inference
- Secretary and Board use local Ollama in the all-local mode

### Debug Scripts

**Best for:** Troubleshooting, development, understanding agent behavior

```powershell
.\engine_tune\run_debug_long.ps1   # Verbose logging
.\engine_tune\run_debug_short.ps1  # Concise debug output
```

Requirements:
- API keys configured
- Enables verbose agent decision logging

## Configuration Variables

Each .env template contains:

```ini
# API Keys
HF_TOKEN=your_huggingface_token
OPENAI_API_KEY=your_openai_key
BOARD_AGENT_API_KEY=your_board_agent_key

# Country Agent
COUNTRY_AGENT_BACKEND=hf_api  # or 'ollama' for local
COUNTRY_AGENT_ENABLED=1
COUNTRY_AGENT_MODEL=Qwen/Qwen2.5-72B-Instruct

# For local mode only:
COUNTRY_AGENT_OLLAMA_URL=http://localhost:11434/api/chat
COUNTRY_AGENT_OLLAMA_MODEL=qwen2.5:14b-instruct

# Secretary Agent
SECRETARY_AGENT_ENABLED=1
SECRETARY_AGENT_MODEL=gpt-4o-mini

# Board Agent
BOARD_AGENT_LLM_ENABLED=1
BOARD_AGENT_MODEL=gpt-4o-mini

# Display & GUI
DISPLAY_MODE=full  # or 'short'
GUI_ENABLED=1      # or '0'
DEBUG_MODE=0       # or '1' for debug
```

## Customizing Templates

To create your own configuration:

1. Copy an existing template:
   ```powershell
   Copy-Item .env.api_gui_long .env.custom
   ```

2. Edit the file with your settings

3. Create a run script:
   ```powershell
   Copy-Item engine_tune\run_api_gui_long.ps1 engine_tune\run_custom.ps1
   ```

4. Update the script to use your template:
   ```powershell
   Copy-Item -Path ".env.custom" -Destination ".env" -Force
   ```

## Troubleshooting

### "Configuration not found"
Make sure you're running from the project root directory where .env templates are located.

### "Module not found"
Activate your conda environment first:
```powershell
conda activate waragent
.\engine_tune\run_api_gui_long.ps1
```

### GUI doesn't appear
- GUI only works with API backend (not local/ollama)
- Check that `GUI_ENABLED=1` in the template
- Ensure Pygame is installed: `pip install pygame`

### Slow performance with GUI
Use API backend instead of local. GUI is auto-disabled with local agents for performance.

### "Ollama connection refused"
For local scripts, make sure Ollama is running:
```powershell
ollama serve
```

## Security Note

**IMPORTANT:** 
- Never commit `.env` or `.env.*` files with real API keys to version control
- The templates in this project contain placeholder keys
- Replace them with your actual keys before use
- Add `.env` to `.gitignore` (already configured)

## Old Scripts

The old `mode_run_*.ps1` scripts that set `$env:` variables are deprecated but still functional. The new `run_*.ps1` scripts using .env files are recommended for easier configuration management.
