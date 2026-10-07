# Anchor top-bar gear landed - October 6, 2026

Code job 20261006-200005-42be96 finished Foreman wave 1 GO and landed as 6126fec. The gate `python -m pytest -v tests/test_provider_setup_anchor_shell.py tests/test_provider_setup_browser.py` passed. Snapshot: refs/anchor-snapshots/20261006-203952-2cede4.

The previous implementation placed the gear only in Cave's framed page, leaving Anchor's own upper-left title bar without a gear. The repair adds the gear left of the Anchor mark in the production app shell and opens the saved Setup with singleton reuse. Tests cover desktop/narrow placement, keyboard opening, retained settings, composer draft preservation and returning to Cave; display-only GET and POST guards prevent unwanted work.

John's currently open Anchor window was not captured. The code is landed, not confirmed live on his screen. The completion notice reserves activation for an Anchor restart on John's word or his standing restart-when-idle authorization. No restart, forced reload, session kill, slice close or acceptance was performed. Existing-window activation and verification remain next.

The runner again landed its temporary root foreman.config.json. With Anchor's job ownership released, restored the exact c1c0276 bytes and verified SHA256 fc14e59db8f6c50fbd6ed3dd7b0d260da7a1d90293c551f5d2e8dd157bf8ddf4. Registered the existing Foreman evidence in DELIVERABLES.md. Attention returned to quiet. Session overhead count is 3 (missing-gear correction, running/location follow-up, and October 7 running-status follow-up).

October 7 pickup: re-read all 58 durable turns and the Face, roadmap, Strip and deliverables register. The gear job remains done and landed; there are no busy repositories. The running service stamp is c210009, predating the gear landing. No new build, restart, reload or slice close was initiated. Next remains an authorized Anchor restart followed by verification in the existing client.
