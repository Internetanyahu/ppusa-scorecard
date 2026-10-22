# PPUSA-SCORECARD — Permanent AI / Maintainer Instructions

**READ THIS FILE FIRST before changing this repository.** Treat these rules as persistent project requirements. They apply to every connected AI, coding agent, automation, and future maintenance pass.

## 1. Site appearance is permanently dark

- This is a dark-mode website. Do not introduce white-on-white, black-on-black, or otherwise low-contrast UI.
- Text, labels, inputs, selects, buttons, dialogs, admin screens, login screens, notices, and dynamically injected UI must remain readable against the dark theme.
- Any new component must inherit the existing dark design tokens where possible.
- If a third-party/default browser style would make a control light, explicitly style it for the dark theme.

## 2. The scorecard-set swapper belongs to the page

- The scorecard set selector must be part of the normal page content/toolbars.
- It must NOT be a floating widget pinned to the viewport, an absolute-positioned overlay, or something that sits above the rest of the page.
- It should scroll naturally with the page and remain usable on mobile.
- Preserve dark-mode contrast for the selector.

## 3. Admin UI must match the dark site

- The admin panel and especially the login/unlock screen must use the same dark visual language as the public site.
- Never ship a default light login form.
- Check dynamically injected admin CSS/HTML as well as linked stylesheets; later-injected styles can override the normal theme.

## 4. Player data and offices

- Keep every player/profile returned by Power Play USA, including people who are not currently in office.
- Do not infer office counts from the number of profiles.
- Office counts must represent actual offices exposed by the Power Play USA politician/profile data, including POTUS, Vice President, Governor, and other office types when present.
- A profile with no office must explicitly display **No office**.
- Do not silently discard profiles because they lack a current office.
- Preserve as much source profile information as practical instead of reducing the scraper to Senate/House-only fields.
- The public player card must render the compiled office count directly and must not briefly show the old profile-count label while an asynchronous decoration step runs.
- The `examples/` directory contains saved Power Play source pages and is a schema reference. Use it before guessing at DOM or embedded-data structure.
- The politician source example demonstrates that `window.politiciansData` contains roster data but does **not** itself guarantee office information. Office data must come from actual office/profile fields or individual Power Play profile pages; never invent an office from party, caucus, state, or `is_main`.

## 5. Power Play USA security verification is a hard failure

- If Power Play USA returns a security verification page containing language such as `Performing security verification` or `This website uses a security service to protect against malicious bots`, stop the relevant scraper.
- Do not interpret the verification page as a missing bill, empty profile, or legitimate source record.
- Do not keep retrying the same blocked page.
- Emit a large, explicit error identifying security verification and exit non-successfully so the workflow cannot quietly publish bad data.

## 6. Scraper correctness beats silent recovery

- Never turn a source failure into plausible-looking empty data.
- Preserve source records unless there is a documented reason to remove them.
- When the source schema is uncertain, inspect the actual page/source data or use the supplied page-source examples rather than guessing a narrow schema.
- Prefer broad extraction plus normalization over brittle hard-coded field lists.
- The saved bill source is a parser fixture. It contains the actual `About This Bill`, sponsor/cosponsor, provisions, and Senate/House vote DOM used by the bill parser.

## 7. Resolution provision monitoring

- `scraper/resolutions.py` scrapes `https://powerplayusa.net/chambers/create-resolution` as a game-schema canary.
- `.github/workflows/resolutions.yml` runs that scraper every 3 calendar days and can also be run manually.
- `resolution_provisions.json` records the current provision catalog and additions/removals between checks.
- New provision names must not be silently ignored; they are a signal that scorecard classification may need an update.

## 8. Appropriations are neutral for now

- Bills identified as appropriations are neutral in the compiled scorecard until a dedicated policy rule is defined.
- Appropriations must not add positive or negative points to player scores.
- `scraper/neutralize_appropriations.py` enforces this after scorecard compilation and before scorecard sets are built.
- Neutral appropriations must have direction `0`, `scorable: false`, and `Neutral / mixed` bill alignment.

## 9. Saved source examples are part of the test contract

- `examples/powerplayusa.net_national_politicians.txt` is the reference source for the national politician roster parser.
- `examples/powerplayusa.net_resolutions_1.txt` is the reference source for the bill/resolution parser.
- `examples/powerplayusa.net_chambers_create-resolution.txt` is additional Power Play source context for chamber/resolution structure.
- `scraper/validate_powerplay_examples.py` must pass before live scraping is allowed by the workflows.
- If Power Play changes its HTML or embedded data schema, update the parsers against the supplied source examples first, then update the fixtures/tests if necessary.

## 10. Preserve existing functionality

- Make targeted changes. Do not replace working behavior merely to simplify an implementation.
- Before changing a file, inspect its current contents and preserve unrelated logic.
- Keep scorecard-set selection, score calculation, bill data, profile data, and admin functionality working together.
- Do not hardcode secrets, passwords, API tokens, or credentials into the repository.

## 11. Validation checklist

Before considering a change complete, verify:

1. Public site remains dark and readable.
2. Scorecard set selector is inside normal page flow and scrolls with the page.
3. Admin login is dark and readable.
4. No light browser-default controls have leaked into the UI.
5. Player records are not lost because they have no current office.
6. Office counts come from office data, not profile count.
7. `No office` appears for office-less profiles.
8. Player cards do not flash the obsolete profile-count office label before compiled office metadata is applied.
9. Power Play security verification causes an explicit scraper failure, not an empty result.
10. Saved Power Play source fixtures parse successfully.
11. Appropriations are direction `0` and non-scorable in published scorecard sets.
12. Resolution provision monitoring remains scheduled every 3 calendar days.
13. Workflows still reference the intended generated files and build steps.

## 12. Source of truth for future AIs

This file is the first project-level instruction document to read. If another document conflicts with these permanent UI/data-integrity rules, stop and resolve the conflict rather than silently weakening these requirements.

> **Visibility note:** Git cannot make a tracked repository file visible only to its owner and AIs. If this repository is public, this file is public too. Do not put passwords, tokens, private keys, or other secrets here. The purpose of this file is to give connected AIs a durable, repository-local instruction source.
