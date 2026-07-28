# Wave 2 Inventory Table

This table enumerates every inline stakes literal and heuristic previously hardcoded in `run-rounds.mjs`, and maps them to a formal governor output field or rule.

| Inline Literal / Heuristic in `run-rounds.mjs` | Mapped to formal governor output field / rule | Notes |
| :--- | :--- | :--- |
| `8` (default max rounds) | `roundBudget` output field | `formal-governor.mjs` was extended to encode the default `8` budget. |
| `loopThresholds()` fallback (N, K, M defaults) | `thresholds` output field | The governor now imports and uses `loopThresholds` if not explicitly provided. |
| `{ declared_stakes: 'high', ... }` (default stakes) | `tier` output field | The fallback default stakes logic was moved into the governor, which computes and outputs the `tier`. |
| `resolveTier(...)` (local tier resolution) | `tier` output field | The governor encapsulates this logic and `run-rounds.mjs` just reads `contract.tier`. |

This inventory is asserted automatically by the `test/wave2.test.mjs` completeness test and static lint guard.