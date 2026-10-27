# cst-rewrite

Best-in-class programmatic code-rewriting and verification tool backing the `Anvil` orchestrator:
1. **`--orange-split <repo>`**: Runs the **Parable of the Oranges** decomposition, classifying every function into **Juice** (essential `Do-Analysis` domain logic), **Peel** (`Get-Data` / `Create-Output` surface contracts), and **Pith & Seeds** (unreferenced legacy scaffolding / `Null Space` candidates).
2. **`--source <file.py> [--rename old:new] [--drop fn_name]`**: Executes a lossless Concrete Syntax Tree (`LibCST` / `parso`) transformation that preserves 100% of comments, docstrings, and formatting on untouched nodes, followed by a `ruff` syntax & undefined-name gate.
3. **`--verify-equivalence <old_repo> <new_repo>`**: Runs property-based (`Hypothesis`) and deterministic input-output differential equivalence tests across shared functions (`rtol=1e-7`).

## Usage

```bash
python C:/dev/foundry-tools/ft.py cst-rewrite --orange-split C:/dev/MyProject
python C:/dev/foundry-tools/ft.py cst-rewrite --source app.py --rename legacy_calc:compute_signal --drop _unused_helper
python C:/dev/foundry-tools/ft.py cst-rewrite --verify-equivalence C:/dev/OldRepo C:/dev/NewRepo
```
