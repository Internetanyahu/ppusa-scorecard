# Deterministic Conservative Scorecard Workflow

## Core rule

Only **finalized** bills are scored. Proposed, active, or committee-stage bills cannot affect a politician's score.

Every provision receives the same weight:

- **+1** = moves policy to the right of the current-law baseline.
- **-1** = moves policy to the left of the current-law baseline.
- **0** = neutral or no material policy movement.

A neutral provision does not enter the denominator.

For each scored provision:

- Aye on **+1** = aligned.
- Nay on **-1** = aligned.
- The opposite vote = not aligned.

This means a bill containing both right- and left-moving provisions is scored provision-by-provision rather than being forced into one bill-level direction.

## Categories

### Social
Social conservatism, nationalism, law and order, gun rights/open carry, religious liberty, parental rights, and immigration restriction.

### Economic
Fiscal libertarianism, lower taxes, spending restraint, deregulation, and free enterprise. **Protectionism is an explicit exception and is scored rightward.**

### Foreign
Strong defense and intelligence capability, anti-communism, and hemispheric defense. The workflow is **generally anti-intervention**: military readiness is rightward, while overseas intervention, invasion, occupation, and regime-change policy are leftward unless a specific calibrated rule says otherwise.

## Calibration decisions incorporated

The flagged finalized bills were manually resolved into deterministic rules, including:

- Assault rifles/open carry: **+1 Social**.
- Abortion access: **-1 Social**.
- New environmental/regulatory standards: **-1 Economic**.
- $15 minimum wage: **-1 Economic**.
- VA benefit expansion: **-1 Economic**.
- H-1B 200,000 where the source labels immigration status quo: **0**.
- Medicare for All: **-1 Economic**.
- Superfund industry excise tax: **-1 Economic**.
- Communist Party ban: **+1 Social**.
- Federal Election Day holiday: **-1 Social**.
- DC statehood: **-1 Social**.
- Union dues expansion/tax deductibility: **-1 Economic**.
- TikTok ban: **+1 Foreign**.
- Independent special prosecutor/anti-corruption oversight: **+1 Social**.
- Full intelligence program authority: **+1 Foreign**.
- GI Bill full tuition/housing expansion: **-1 Economic**.
- Afghanistan/al-Qaida AUMF: **-1 Foreign** because it represents overseas military projection.
- Bills with no policy provisions or provisions that merely freeze current funding levels: **0 / no scored provisions**.

## Automation

`.github/workflows/scorecard.yml` runs daily and can also be run manually. It scrapes the data, rebuilds legislative history, applies `scorecard_rules.json`, validates the outputs, and commits the updated scorecard.

Unknown or conflicting provisions are not guessed. They are written to `scorecard_review.json` for future calibration.

## Tier thresholds

- **S:** 90–100
- **A:** 80–89.99
- **B:** 70–79.99
- **C:** 60–69.99
- **D:** 50–59.99
- **F:** 0–49.99
