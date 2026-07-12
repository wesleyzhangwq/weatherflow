# MiniMax model configuration

WeatherFlow uses MiniMax through its OpenAI-compatible Chat Completions API.
The default production model is `MiniMax-M3`. WeatherFlow currently consumes
its text and tool-calling subset. Other models can still be selected explicitly
when the account exposes them.

M3 thinking is explicitly disabled in OpenAI-compatible requests. This avoids
the provider requirement to replay hidden reasoning during multi-turn tool use
and preserves WeatherFlow's rule that chain-of-thought never enters durable
history.

## Choose the matching endpoint

- International account created at `platform.minimax.io`:
  `https://api.minimax.io/v1`
- Mainland China account created at `platform.minimaxi.com`:
  `https://api.minimaxi.com/v1`

Do not move a key between regions unless the MiniMax account confirms that the
key is valid on that endpoint.

## Configure a source checkout

For a Mainland China account:

```bash
pnpm model:configure:cn
```

For an international account:

```bash
pnpm model:configure
```

Both commands select `MiniMax-M3`, use a hidden API-key prompt, and store the
credential in macOS Keychain. Start the development app with:

```bash
pnpm dev:app
```

This starts the Vite frontend, debug Tauri shell, and reloadable Python core
from source. Check the non-secret model status with `pnpm model:status`.

## Configure the installed app

Quit WeatherFlow, then run the standalone daemon inside the installed app:

```bash
/Applications/WeatherFlow.app/Contents/MacOS/weatherflow-core \
  --data-dir "$HOME/.local/share/weatherflow" \
  configure-minimax \
  --model MiniMax-M3 \
  --base-url https://api.minimax.io/v1
```

For a Mainland China account, replace the base URL with
`https://api.minimaxi.com/v1`.

The command prompts for the API key with terminal echo disabled, validates the
key and selected model through `GET /v1/models`, and then stores the key in
macOS Keychain under service `ai.weatherflow.minimax`. SQLite retains only the
model, base URL, version, and `minimax.api_key` reference.

Check the non-secret status:

```bash
/Applications/WeatherFlow.app/Contents/MacOS/weatherflow-core \
  --data-dir "$HOME/.local/share/weatherflow" model-status
```

Reopen WeatherFlow. Cockpit should show `minimax · MiniMax-M3` instead of
`Echo smoke fallback`.

## Runtime boundary

The adapter exposes only the Run's frozen `ToolSpec` set. WeatherFlow tool IDs
are converted to deterministic provider-safe function names and mapped back
before dispatch. MiniMax can request at most one tool or one bounded leaf
delegation per turn; the existing Trust Plane still decides allow, sandbox,
approval, or deny.

MiniMax reasoning fields and `<think>` blocks are deliberately not persisted.
Only final text, tool/delegation intent, bounded observations, and usage enter
the durable WeatherFlow runtime.
