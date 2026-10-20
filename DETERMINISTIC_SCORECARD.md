# Deterministic Conservative Scorecard Workflow

## Core rule

Only **finalized** bills are scored. Proposed, active, or committee-stage bills cannot affect a politician's score.

Every provision receives the same weight and exactly one binary direction:

- **+1** = conservative/rightward.
- **-1** = liberal/leftward.
- **0 is never a valid provision score.**

A comparable prior enacted bill is recorded as the **current-law reference** when one exists. When no comparable prior law exists, the configured ideological rule/fallback determines the direction. Every provision remains auditable in `conservative_scorecard.json`.

For each scored provision:

- Aye on **+1** = aligned.
- Nay on **-1** = aligned.
- The opposite vote = not aligned.

A bill containing both right- and left-moving provisions is scored provision-by-provision rather than being forced into one bill-level direction.

## Provision options are not scraped

The bill scraper is intentionally separate from the scorecard compiler.

- `.github/workflows/bills.yml` is the only workflow that updates `bills.json` from Power Play USA.
- `.github/workflows/scorecard.yml` consumes the checked-in `bills.json` and **does not scrape or invent provision options**.
- New provision options should be added manually to the deterministic rules when the game itself is updated.

## Categories

### Social
Social conservatism, nationalism, law and order, gun rights/open carry, religious liberty, parental rights, and immigration restriction.

### Economic
Fiscal libertarianism, lower taxes, spending restraint, deregulation, and free enterprise. **Protectionism is an explicit exception and is scored rightward.**

### Foreign
Strong defense and intelligence capability, anti-communism, and hemispheric defense. The workflow is **generally anti-intervention**: military readiness is rightward, while overseas intervention, invasion, occupation, and regime-change policy are leftward unless a specific calibrated rule says otherwise.

## Calibration decisions incorporated

The calibrated rules in `scorecard_rules.json` include the prior manual decisions, including:

- Assault rifles/open carry: **+1 Social**.
- Abortion access: **-1 Social**.
- New environmental/regulatory standards: **-1 Economic**.
- $15 minimum wage: **-1 Economic**.
- VA benefit expansion: **-1 Economic**.
- H-1B 200,000: **-1 Social** under the nationalist immigration framework.
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

No finalized provision is assigned zero, even where the source describes the option as neutral or status quo. Such cases use the configured binary rule and can be manually recalibrated later.

## Website-ready output

The scorecard workflow copies the canonical data into `public/data/`:

- `bills.json`
- `conservative_scorecard.json`
- `players.json`
- `voting_records.json`
- `legislative_history.json`
- `scorecard_rules.json`

GitHub Actions also uploads this directory as the `ppusa-scorecard-data` artifact.

## Tier thresholds

- **S:** 90–100
- **A:** 80–89.99
- **B:** 70–79.99
- **C:** 60–69.99
- **D:** 50–59.99
- **F:** 0–49.99
