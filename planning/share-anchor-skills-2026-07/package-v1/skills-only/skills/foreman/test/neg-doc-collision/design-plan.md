# Design-Plan (deliberately ambiguous filename)

This file's basename `design-plan.md` matches BOTH the `description` role
(via the `/design/` pattern) AND the `plan` role (via the `/\bplan\b/` pattern).
Foreman must HALT on this cross-role collision rather than silently binding one
file to two roles (finding J). Name the docs explicitly in `foreman.config.json`
to resolve.

## Wave 1 — placeholder

(unused: locateDocs HALTs before wave parsing is reached)
