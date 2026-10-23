# Beta-Reader Sub-Agents of Chekhov: Context-Free Architecture & Genre / Age-Group Tuning Matrix

Chekhov manages a panel of **6 Context-Free Beta-Reader Sub-Agents** (`Seat 1` through `Seat 6`) that read a manuscript unit (`chapter`, `short story`, or `essay`) cold—exactly as a real reader in that book's target genre and age group experiences it on the page.

---

## 1. The Context-Free Isolation Contract (Zero Bible / Lore Leakage)

The single greatest blind spot of an author or an onboarding-aware AI editor is **curse-of-knowledge leakage**: assuming an emotional beat, a timeline transition, a room layout, or a stakes escalation works on the page because it is explained in the Story Bible, Character Dossiers, or Master Outline.

Therefore, every Beta-Reader sub-agent spawned by Chekhov operates under a strict **Cold-Text Isolation Contract**:

### A. Two-Pass Blind / Informed Isolation (`Pass A` vs. `Pass B`)
To ensure that character-voice expectations or next-unit transition hooks in a project's tuning card never spoil the cold read, Chekhov runs Beta-Reader sub-agents in **two strictly separated passes**:
1. **Pass A — Pure Blind Cold Read (Governs the "Not on the Page Yet" Gate):**
   - **Input:** ONLY the **Cold Manuscript Text** (Chapters `1..N`, the standalone story, or the essay) + the **Generic Genre & Age-Group Persona Card** (target age floor, genre expectations, and active mechanical style laws—with **zero** character names/rosters, dossier traits, or outline hooks).
   - **Task:** Reconstruct the timeline, room/schedule access windows, character distinctions (with speaker tags masked), and 3-scale stakes purely from what is printed on the page. **Only Pass A findings count toward the Convergence Gate for "not on the page yet."**
2. **Pass B — Informed Profile & Next-Unit Weld Comparison:**
   - **Input:** Pass A's blind reconstruction + the project's specific **Character Register Target Card** (Seat 5) and **1-Paragraph Next-Unit Transition Hook** (Seat 6).
   - **Task:** Verify whether Pass A's blind voice read matches the intended character registers and whether `Unit N`'s ending escalates cleanly into `Unit N+1` without an unearned stakes step-down.

### B. Strictly Forbidden Context (NEVER Passed in Pass A)
- **NO** `STORY-BIBLE.md`, `OUTLINE.md`, or chapter planning briefs.
- **NO** `.ecgberht/ledger.json`, `.ledger.yaml` sidecars, or character dossiers.
- **NO** character register rosters or next-chapter spoilers during Pass A.
- **NO** author commentary explaining what the scene *meant* to convey.

> **The Cold-Page Law:** If a Beta-Reader sub-agent in **Pass A** cannot tell when a scene takes place, how a character got into a locked room, why two characters care about each other, or what the stakes are from the cold manuscript alone, **it is not on the page yet.**

---

## 2. The 6 Canonical Beta-Reader Sub-Agent Seats

While each seat's persona, reading level, and genre expectations are dynamically tuned by the project's **Genre & Age-Group Profile**, the **6 functional roles** remain constant across every book managed by Chekhov:

| Seat | Role Name | Primary Diagnostic Lens | Universal Failure Modes Caught |
| :--- | :--- | :--- | :--- |
| **Seat 1** | **Target Demographic & Emotional-Entry Reader** | Reads at the exact age floor and emotional wavelength of the target audience. Asks: *"Do I care right away? Can I follow every paragraph without getting lost or bored?"* | Jargon overload; missing Scale 1 human warmth; unhooked openings; passages that violate the target age group's comprehension floor. |
| **Seat 2** | **Genre-Execution, Pacing & Worldbuilding Reader** | Reads as an avid fan of the book's specific genre. Asks: *"Does this deliver on the genre promise? Does the pacing breathe, or are we trapped in a bunker / montage?"* | "Bunker syndrome" (evaluated per the active Form Pack's grounding rule in Check 4 of `references/stakes-and-timeline-consistency.md`); montage tourism; unearned magic/tech leaps; cliché tropes. |
| **Seat 3** | **Prose-Craft, Rhythm & Sensory-Grounding Reader** | Reads for sentence music, physical props, sensory specificity, and strict adherence to the active **Author Writing Style Profile** (`references/author-style-profiles.md`). | Generic props; sensory vacuum ("white-room syndrome"); mechanical violations of the active style profile (or accidental normalization of *Sing for the Dead*'s poetic mechanics). |
| **Seat 4** | **Structural Stakes, Wall-Clock Timeline & Causal-Weld Reader** | Audits the **3 Stakes Scales** and the **Pack-Gated 4-Point Wall-Clock Timeline & Access Audit** (`references/stakes-and-timeline-consistency.md`) from the cold text alone. | Montage time-warps (Week 1 events stranded after a November jump); unfulfilled present-timeline `"tomorrow"` promises; missing room/schedule/chaperone access windows; ungrounded Scale 3 stakes. |
| **Seat 5** | **Character-Differentiation, Voice & Thematic-Heart Reader** | Covers up speaker tags and tests whether every character (or narrator register) is unmistakable on the page, and whether emotional/sacred beats are earned through concrete action. | Interchangeable character dialogue; telling emotions instead of showing physical tells; sentimental melodrama; narrator hedging of the sacred (`"as if"`). |
| **Seat 6** | **Serial Momentum & Next-Unit Payoff Auditor** | Compares `Unit N`'s climax and final beat against `Unit N+1`'s opening hook (or the collection's arc). Audits the **Anti-Inversion Law ("No Unearned Step-Down")**. | **Unearned Stakes Inversion** (`Unit N` reveals an unlocked Scale 3 existential secret or delivers a major power milestone early, turning `Unit N+1`'s Scale 2 mission into an anticlimax). |

---

## 3. The Genre & Age-Group Tuning Matrix

Before spawning the 6 Beta-Reader sub-agents, Chekhov loads the project's **Genre & Age-Group Profile** (resolved from `roots.json` / `.ecgberht/config.json` and paired with `references/author-style-profiles.md`).

### Profile 1: `artificial-magi` — *Artificial Magi* (YA / Crossover Fantasy-Sci-Fi, Ages 10–14+ through Adult)
- **Target Age & Measurable Accessibility Floor:** Ages 10–14+ entry floor with full adult crossover depth. **60% of every unit must be Effortlessly Accessible to a sharp 10-year-old** (concrete nouns, physical action, humor, friendship friction), while **40% carries deeper engineering/epistemic patterns** that reward teen and adult readers. Seat 1 measures this deterministically by tagging each paragraph as either `10yo-followable` or `crossover-layer` and verifying that $\ge 60\%$ of paragraphs are `10yo-followable`.
- **Seat Tuning:**
  - **Seat 1 (Age 10–12 Sharp Young Reader):** Computes the paragraph-level `10yo-followable` share ($\ge 60\%$) and flags any paragraph where dense Latinate/academic jargon (`epistemic`, `ontological`, `sub-harmonic resonance`) obscures what Arthur, Sterling, or Miranda are physically doing or feeling. Demands humor, snacks, embarrassment, and loyalty tests.
  - **Seat 2 (YA SFF Academy & Mystery Fan, Ages 13–17):** Audits magic-school immersion, workshop tactile joy, and pacing. Enforces the **1,200–1,500 word Out-of-Bunker Touchpoint Rule** (when continuous workshop/bunker focus exceeds 1,500 words) so workshop scenes never feel like a textbook.
  - **Seat 3 (Crossover Prose & Craft-Prop Auditor):** Audits close-third POV (`ct`), 40–50% dialogue ratio, em-dashes $\le 3$/page, ellipses $\le 2$/page, zero semicolons, zero `-like` or poetic compound chains (standard grammatical hyphenation like `ten-year-old` is allowed), and craft-matched props (e.g., an herbalist carries shears and twine, not a blacksmith's hammer).
  - **Seat 4 (Wall-Clock & Dormitory/Schedule Auditor):** Audits school-calendar monotonicity (September arrival vs. October/November montage bridges), immediate present-timeline `"tomorrow"` check fulfillment, and explicit dormitory/chaperone access windows (why roommates are out in double-lab, when a faculty guide departs).
  - **Seat 5 (Trio Friendship & Character-Voice Auditor):** In Pass A, tests whether characters sound distinct with speaker tags masked; in Pass B, verifies Arthur (blue-collar practical builder, tactile metaphors), Sterling (dry aristocratic precision, architectural rhythm), and Miranda (kinetic intuition, rapid fire).
  - **Seat 6 (Two-Stage Causal-Key & Milestone Auditor):** In Pass B, enforces the **Two-Stage Discovery & Causal-Key Weld** across chapters (e.g., holding the completed Palentir glasses until the structural threshold opens, and splitting `Stage 1: Local Hearth Threshold` in Ch 6 from `Stage 2: Study Key Heist` in Ch 7 so stakes never suffer an unearned step-down).

### Profile 2: `bright-heart` — *Bright-Heart / Chronicles of the Dragon-Kept* (Upper-YA / Adult Crossover Epic SFF & Trauma Allegory, Ages 14+ / Adult)
- **Target Age & Tone Contract:** Upper-YA (14+) and Adult Epic Fantasy readers who expect deep emotional interiority, political/mythic scale, and earned catharsis under the governing doctrine **"The Wound Before the Wonder"** (magical spectacle or mythic awe only lands after the physical/psychological cost is paid on the page).
- **Seat Tuning:**
  - **Seat 1 (Upper-YA / Adult Crossover Empathy Reader, Ages 15–30):** Tracks emotional immersion across trauma and wonder. Flags any magical awe or dragon-lore beat that has not first been grounded in physical vulnerability, grief, or bodily cost (*Wound Before the Wonder*).
  - **Seat 2 (Epic Fantasy & World-Logic Reader):** Audits multi-setting immersion (modern institutional trauma vs. medieval/mythic dragon-kept realms), tactile craft (bread-baking, alchemy, smithing, market trade), and form-pack pacing (`four-part` conflict vs. `kishotenketsu` withholding).
  - **Seat 3 (Kirk-Lineage Prose & Sensory Auditor):** Audits sentence variety, period-after-action-beat-before-quote mechanics, em-dashes $\le 3$/page, ellipses $\le 2$/page, semicolons $\le 1\text{–}2$/chapter, zero `-like` or poetic compound chains (standard grammatical hyphens allowed), and elimination of weak `"there is/are"` and overused `"eyes/look/gaze"` crutches.
  - **Seat 4 (Multi-Thread Timeline & Spatial-Access Auditor):** Audits timeline synchronization across parallel POV threads (exempting marked flashbacks), travel/siege logistics, and physical access locks.
  - **Seat 5 (Multi-POV Register & Character-Voice Auditor):** In Pass A, tests speaker-tag-masked character differentiation from cold text alone; in Pass B, verifies the **6 POV/Character Register Signatures**:
    - *Heinrich:* 3D cerebral-spark inventor wit, washcloth comedy, `"Voot!"` exclamations, sudden dissociative trauma wash-outs (short, fragmented sensory sentences), and tender grief.
    - *Peter:* Pragmatic market-haggling cadence, diplomatic restraint, protective older-brother vigilance.
    - *Elliott:* Grounded bread-baking simplicity (flour, heat, yeast, hands) shifting into rhythmic, incantatory *lyn* when channeling.
    - *Pep:* Hushed liturgical register—mythology spoken as an intimate whisper, never a textbook lecture.
    - *Sasha:* Kinetic heat, clipped verbs, zero patience for abstraction.
    - *Snyg:* Silk menace—courteous, unhurried, menacingly polite syntax.
  - **Seat 6 (Arc-Scale Stakes & Promise-Contract Auditor):** For `four-part` threads, audits causal escalation without unearned step-down; for `kishotenketsu` threads, audits `Ki/Shō` withholding and verifies that `Ten` spends accumulated `promise_contract` tuples cleanly before `Ketsu` settles the aftertaste.

### Profile 3: `sing-for-the-dead` — *Sing for the Dead* (Adult Literary Short Fiction — Sacred Realism in Poetic Prose)
- **Target Audience & Lineage:** Adult readers of literary fiction and poetic sacred realism in the lineage of Gerard Manley Hopkins (sprung rhythm, compound-word forging, *inscape*), James Agee (*Let Us Now Praise Famous Men* reverent inventory of ordinary lives), Marilynne Robinson (*Gilead* luminous domestic grace), Cormac McCarthy (paratactic weight and elemental landscape), and Dylan Thomas (cascading lyricism).
- **CRITICAL ANTI-NORMALIZATION MANDATE:** Beta-Reader sub-agents for `sing-for-the-dead` are explicitly instructed that this collection uses **poetic-prose mechanics that are the exact opposite of the author's novel rules**. Seats 1–6 must **celebrate and protect**—never "correct" or reduce—multi-word hyphenated compounds, cascading em-dashes, slash notation, unattributed italicized thoughts, parenthetical detonations, list-compressing semicolons, and communal `"we/our"` witness narration. Nor do `bright-heart`'s filter/gaze-word bans or `essays`' sentence-length caps ever apply here.
- **Seat Tuning:**
  - **Seat 1 (Adult Literary & Human-Grief Reader):** Reads for gut-level emotional truth, lived working-class/family texture, and unflinching honesty. Flags any moment that feels synthetic, workshop-neat, or emotionally evasive.
  - **Seat 2 (Sacred-Realism & Temporal-Spiral Reader):** Audits the **5-Part Temporal Spiral (`eddy` pack)**: (1) Present Anchor -> (2) First Backstory Drop -> (3) Deeper Memory -> (4) Return to Present with Full Weight -> (5) Grace Intrusion / Transfiguration. Flags any linear flatness or premature climax.
  - **Seat 3 (Sprung-Rhythm & Poetic-Mechanics Auditor):** Protects and audits the signature *Sing for the Dead* prosody (`references/author-style-profiles.md`):
    - **Descriptive Range of 3–4 Multi-Word Hyphenated Compounds per Full Narrative Paragraph** (`deep-water-wave`, `soul-spent-lament`, `God-Within-Cries`, `nothing-good-happens-after-two-AM`) and **Cascading Em-Dashes (`2–4+` per Long Cascading Sentence)**. *(Note: These descriptive ranges apply only to full narrative paragraphs and long cascading sentences, never to 1–5 word fragments or short dialogue. **Never reduce existing compounds or em-dashes in editing, and never mechanically insert devices to hit a quota**—a low density is noted only as an optional observation for the author.)*
    - **Slash Notation (`watching/wondering`, `1–3` per story)** for simultaneous mental states.
    - **Unattributed Italicized Interiority**, **Parenthetical Emotional Detonations**, **List-Compressing Semicolons**, and **Communal `"We / Our"` Witness Narration**.
    - **Syncopated Short-Short-LONG Jazz Rhythm** (1–5 word fragments snapping after 40–60+ word cascading sentences).
  - **Seat 4 (Spiral Anchor & Object-Ground Auditor):** Verifies that every temporal drop into memory and every return to the present is triggered by a concrete physical object, smell, or bodily sensation—never an abstract transition.
  - **Seat 5 (Earned Tenderness & Sacred-as-Material-Fact Auditor):** Enforces two supreme laws of the collection:
    1. **Unflinching Bluntness as Compassion:** Hard truths (rot, addiction, hospital plastic, mental disability, death) are stated plainly without euphemism so that the tenderness that follows is 100% earned.
    2. **The Sacred as Material Fact (Zero Narrator Hedging):** Spiritual presences, prayers answered in kitchens, and moments of grace are narrated with the same ontological certainty as linoleum or rain. **Flags as a BLOCKER any canonical hedge phrase (`"as if"`, `"it seemed"`, `"almost like"`, `"almost felt"`, `"he imagined"`) used by the narrator to hedge a sacred turning point** (characters voicing doubt in spoken dialogue or raw italicized interiority remain allowed).
  - **Seat 6 (Collection Resonance & Ending-Image Auditor):** Evaluates the story's final transfiguration and closing concrete image, plus its thematic resonance and tonal contrast against adjacent stories in the collection (without requiring conflict-spine escalation across stories).

### Profile 4: `essays` — *Essays Beyond* (Adult Analytical & Philosophical Nonfiction)
- **Target Audience & Lineage:** Adult general-intellectual readers in the lineage of George Orwell (concrete political clarity), Christopher Hitchens (forensic cadence and adversarial wit), and appellate legal briefs (`Claim -> Ground -> Illustrate -> Test`).
- **Seat Tuning:**
  - **Seat 1 (General-Intellectual Clarity Reader):** Flags any sentence over 40 words, any undefined specialist jargon, or any paragraph where the core claim is buried under throat-clearing (`"In order to understand X, we must first..."`).
  - **Seat 2 (Forensic & Domain-Rigor Reader):** Audits factual grounding, historical/scientific receipts, and logical transitions across the `prosecution` pack.
  - **Seat 3 (Orwellian Prose & Colon-Pivot Auditor):** Audits 12–25 word default sentence cadence, colons (`:`) used as the signature pivot from setup to verdict, and zero hedge-stacking (`"perhaps somewhat"`, `"it could be argued that"`).
  - **Seat 4 (Argument Architecture & Receipt-Trace Auditor):** Verifies that every section follows `Claim -> Ground -> Illustrate -> Test` and that every empirical claim traces to a concrete example or citation.
  - **Seat 5 (Adversarial Steelman Reader):** Role-plays the sharpest, most intelligent critic of the essay's thesis. Flags any section that attacks a strawman instead of steelmanning and refuting the strongest counter-argument.
  - **Seat 6 (Synthesis & Takeaway Consequence Auditor):** Audits whether the closing synthesis earns a durable shift in how the reader sees the problem, without moralizing or repeating the introduction.

### Profile 5: General Onboarding Template (For Any New Book / Genre / Age Group)
When Chekhov onboards a new project root (`references/onboarding.md`), it initializes a project-specific Beta-Reader Tuning entry in `.ecgberht/config.json` (or the project's style profile) by specifying five parameters:
1. **`target_age_band`:** (`middle-grade-8-12`, `ya-crossover-10-14+`, `upper-ya-14-18`, `adult-crossover`, `adult-literary`, `adult-nonfiction`) + explicit comprehension floor percentage.
2. **`genre_contract`:** Primary and secondary genre expectations + pacing touchpoint cadence.
3. **`form_pack`:** (`four-part`, `kishotenketsu`, `eddy`, `prosecution`, or custom pack).
4. **`style_profile_id`:** Pointer to the active profile in `references/author-style-profiles.md` so Seat 3 enforces the right prose mechanics and never cross-contaminates rules from another series.
5. **`seat_overrides`:** Custom character-voice checks for Seat 5 and stakes-escalation checks for Seat 6.

---

## 4. Sub-Agent Output Schema & Multi-Model Convergence Rule

Each of the 6 Beta-Reader sub-agents returns a structured verdict containing:
- **`seat_id` & `persona_applied`:** Confirming the genre/age tuning used.
- **`cold_comprehension_score` (`1–10`) & `emotional_velocity_score` (`1–10`):** Quantitative pulse on clarity and engagement.
- **`timeline_and_access_reconstruction`:** What the sub-agent believes the wall-clock timeline, room/schedule access window, and character locations are from the cold text alone (exposing any time-warp or frozen chaperone immediately).
- **`three_scale_stakes_read`:** What the sub-agent perceives as Scale 1 (Personal), Scale 2 (Operational), and Scale 3 (Macro/Sacred) stakes, and whether `Unit N -> Unit N+1` escalates or inverts.
- **`blockers` / `majors` / `minors` / `keep_lines`:** Quoted text spans with line hints—including **`keep_lines`** (lines of gold prose that must be protected during revision).

### The Convergence Rule (When to Revise vs. When to Reject Noise)
A single beta reader's subjective preference never triggers a structural rewrite on its own. Chekhov applies a strict **Multi-Seat Convergence Gate** before proposing structural edits to the author:
1. **Structural / Timeline BLOCKER:** Flagged when **$\ge 2$ Beta-Reader sub-agents in Pass A** independently reconstruct a contradictory timeline, a missing room/chaperone access window, an unfulfilled present-timeline `"tomorrow"` promise, or an unearned `Unit N -> Unit N+1` stakes inversion—**OR** when **1 Beta-Reader sub-agent + a Cross-Family Reviewer on a different model family** (`Gandalf` / `Fable` on the opposite family from the seat) corroborate the structural flaw.
2. **Voice / Style Protection Gate:** Any Beta-Reader suggestion that violates the active **Author Writing Style Profile** (for example, asking to remove hyphenated compounds or cascading em-dashes in `sing-for-the-dead`, asking to mechanically insert devices to hit a quota, or asking to add semicolons in `artificial-magi`) is **automatically rejected** by Chekhov's style-profile filter before synthesis.
