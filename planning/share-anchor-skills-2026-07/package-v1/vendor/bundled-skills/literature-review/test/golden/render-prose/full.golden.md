# Research Plan

**Artifact version:** plan-artifact/1

## Scope

Map the evidence on retrieval-augmented generation for clinical decision support.

**AXIS (win condition):** A candidate is falsified if it lacks a prospective clinical evaluation.

## Candidate branches / questions

1. **Question:** Does retrieval grounding reduce hallucinated dosages?
   **Rationale:** The draft names dosage hallucination as the primary safety risk.
2. **Question:** Which retrieval corpus curation policies transfer across hospitals?
   **Rationale:** The notes flag cross-site transfer as unresolved.
3. **Question:** How does citation grounding affect clinician trust?
   **Rationale:** The draft ties adoption to verifiable citations.
4. **Question:** What latency budget keeps RAG viable at the bedside?
   **Rationale:** The methods notes cap acceptable latency at two seconds.

## Sources to beat

- **Zakka et al. 2024 (Almanac)** — The strongest published clinical-RAG evaluation to date.
- **Singhal et al. 2023 (Med-PaLM 2)** — The non-retrieval baseline all clinical LLM work is measured against.

## Foresight receipt

**Dropped/reordered:** A multimodal-imaging branch was dropped.
**Counterfactual cost:** Misses radiology-report evidence if imaging becomes central.
**Stamp:** foresight recorded at derive time

## Seeds

- doi:10.1056/AIoa2300068 — Almanac: Retrieval-Augmented Language Models for Clinical Medicine
- pmid:37460753 — Large Language Models Encode Clinical Knowledge
- arxiv:2305.09617 — Towards Expert-Level Medical Question Answering
