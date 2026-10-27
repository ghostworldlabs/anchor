# model-pricing

Instant local lookup and nightly sync of OpenAI, Anthropic, Google Gemini, and xAI Grok models, small-job tiers, and published API list prices (USD per 1M input, cached input, and output tokens).

## Usage

```bash
python C:/dev/foundry-tools/ft.py model-pricing [--family claude|chatgpt|gemini|grok] [--json]
python C:/dev/foundry-tools/ft.py model-pricing --sync [--target C:/dev/Anchor/steward_cockpit/api_list_prices.json]
```
