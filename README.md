# UK Race & Ballot Tracker

A free, self-updating list of major UK races that tells the run club when ballots open and close. A solo build reaches a usable version in about 2 weekends and a fully automated version in about 6 weeks of evenings. Running costs are £0.

> Always confirm dates on the official site. Not affiliated with any race.

## Development

Requires Python 3.11+.

```bash
py -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python build.py                 # validate races.yaml, write site/ and the .ics feeds
python -m pytest                # run the tests
```

- `races.yaml` is the data. Edit it, then run `python build.py` to check it.
- `schema/races.schema.json` is generated from the Pydantic model in `tracker/models.py`. Run `python build.py --write-schema` after changing the model.
- `site/` is build output and is not committed. GitHub Actions builds and deploys it to GitHub Pages on every push to `main` and once a day. In CI the site address and the "suggest a race" link come from the repo's Pages settings and name, so moving the repo needs no code changes. Local builds use `http://localhost:8000`; preview with `python -m http.server 8000 --directory site`.

---

## Overview

**Problem.** Race and ballot news reaches the WhatsApp group as scattered posts. People miss ballot windows because nobody tracks them in one place.

**Goals**

- One list of 30–60 major UK races with race dates and entry windows
- Reminders before each ballot opens and closes, with no manual effort from members
- Data that updates itself, with a person approving changes
- £0 running costs, using free tiers only

**Non-goals (for now)**

- Every small local race in the UK
- A bot posting inside the WhatsApp group
- User accounts, logins or a mobile app
- Handling race entries or payments

**Success criteria**

- At least 20 club members subscribed to the calendar within a month of launch
- No missed ballot for a listed race in the first season (Sep–Jan)
- Every entry verified against its official page in the last 14 days
- Under 30 minutes a week of maintenance

## Scope and data model

Start with a hand-picked list of about 40 races, chosen by the club. A short, accurate list beats a long one with wrong dates.

**Inclusion rule:** a race joins the list if it is a 10K or longer, in the UK, and either uses a ballot or sells out within weeks. Members can propose others (see Community input).

**Starter candidates** (race months and entry types are approximate; confirm each on its official site in Phase 1):

| Race | Distance | Usual month | Entry type |
| --- | --- | --- | --- |
| London Marathon | Marathon | April | Ballot + charity + good-for-age |
| Manchester Marathon | Marathon | April | General entry |
| Brighton Marathon | Marathon | April | General entry |
| Edinburgh Marathon | Marathon | May | General entry |
| Hackney Half | Half | May | General entry |
| Bath Half | Half | March | General entry |
| Great North Run | Half | September | Ballot |
| Royal Parks Half | Half | October | Ballot + charity |
| Great Scottish Run | Half | October | General entry |
| Cardiff Half | Half | October | General entry |
| London 10,000 | 10K | May | General entry |

International majors (Berlin, Chicago, New York, Tokyo, Sydney, Boston) can be added later as their own category. Their ballots matter to UK runners too.

**Added by the group (Oct 2026):** London Landmarks Half, Kew Gardens 10K, Kew Gardens Half, and three international races: Paris Marathon, Berlin Half Marathon and Milan Marathon. International races carry a `country` and can be filtered on the site.

**Data model.** Each race is one record in `races.yaml`. Each year's edition is its own record, so past dates stay as history.

| Field | Type | Example | Notes |
| --- | --- | --- | --- |
| `id` | string | `london-marathon-2027` | slug + year, unique |
| `name` | string | London Marathon |  |
| `distance` | enum | marathon / half / 10k / ultra / other |  |
| `location` | string | London | city or region |
| `country` | string | France | defaults to `UK` |
| `race_date` | date | 2027-04-25 | blank if unannounced |
| `race_date_end` | date | 2027-04-26 | only for races held over several days |
| `entry_type` | list | ballot, general, charity, gfa |  |
| `ballot_opens` | datetime | 2026-04-27T10:00 | UK time |
| `ballot_closes` | datetime | 2026-05-02T12:00 |  |
| `ballot_results` | date | 2026-07-01 |  |
| `general_entry_opens` | datetime |  | for first-come races |
| `price_gbp` | number | 79 | optional |
| `official_url` | url |  | the page that gets monitored |
| `source_url` | url |  | where the date was seen |
| `status` | enum | unannounced / announced / ballot_open / ballot_closed / sold_out / done |  |
| `last_verified` | date | 2026-10-01 | shown on the site |
| `confidence` | enum | confirmed / expected / estimated | estimated = based on last year |
| `notes` | text |  | short, plain |

The `confidence` field matters most. Before a ballot is announced, the site can show “expected late April, based on 2026” instead of a fake exact date. Only `confirmed` records go into the calendar feeds.

## Architecture and free stack

The whole system is a GitHub repo. A YAML file holds the data, GitHub Actions does the work, pull requests are the review queue and GitHub Pages serves the results. There's no server or database to run.

```mermaid
flowchart LR
    A[Daily page check<br/>GitHub Actions cron] --> PR[Pull request<br/>human review]
    B[Member suggestions<br/>Google Form + Sheet] --> PR
    PR -->|merge| Y[(races.yaml)]
    Y --> S[Static site]
    Y --> C[Calendar feeds .ics]
    Y --> D[WhatsApp digest.txt]
```

Both inputs, the daily page check and member suggestions, end as a pull request. Only a merged PR changes `races.yaml`, and each merge rebuilds the site, the calendar feeds and the WhatsApp digest.

| Layer | Tool | Cost |
| --- | --- | --- |
| Data store | `races.yaml` in the GitHub repo (move to Supabase free tier only if you outgrow it) | Free |
| Scheduler and CI | GitHub Actions (daily cron, build on merge) | Free for public repos |
| Fetch and clean | Python, `httpx`, `trafilatura`; Playwright only for JavaScript-heavy sites | Free |
| Date extraction | Gemini API free tier, Groq free tier, or Ollama locally | Free tier |
| Validation | Pydantic + custom rules | Free |
| Review queue | GitHub pull requests (approve from phone or web) | Free |
| Website | Astro or Eleventy on GitHub Pages (or Cloudflare Pages) | Free |
| Calendar feeds | Python `icalendar` | Free |
| Submissions | Google Forms + Sheets API | Free |
| Email digest (optional) | Buttondown or Resend free tier | Free tier |
| Monitoring | GitHub Actions failure emails; an issue opened when a page goes 7 days without a valid fetch | Free |

## Data pipeline

The pipeline checks each official race page once a day and turns any change into a pull request for a person to approve. Nothing reaches the live site without a review.

1. **Fetch.** A Python script (`httpx`) downloads each `official_url`. It honours robots.txt, sends a clear user agent (e.g. `RunClubRaceBot/0.1 (+repo link)`) and waits a few seconds between requests.
2. **Clean.** `trafilatura` pulls out the main text and drops menus, cookie banners and footers. This keeps hashes stable and LLM prompts short.
3. **Detect change.** Hash the cleaned text and compare it with the hash stored in `state/hashes.json`. If nothing changed, stop; most days nothing will.
4. **Extract.** For changed pages only, send the text to an LLM with a fixed JSON schema (the date fields from the data model). The prompt tells it to return `null` when a date isn't stated, and to quote the sentence each date came from.
5. **Validate.** Check the output with Pydantic. Reject impossible results: a ballot closing before it opens, a race date in the past, or a quoted sentence that doesn't appear in the page.
6. **Propose.** Write the changes to `races.yaml` on a new branch and open a pull request. The PR shows the old value, the new value and the quoted sentence.
7. **Review.** A maintainer checks the PR against the source link and merges it. Merging triggers the site and calendar rebuild.

**Free LLM options** (free-tier limits change often; check before building):

- Google Gemini API free tier (Flash models): enough for a few dozen calls a day
- Groq free tier (open-weight models such as Llama)
- Local model through Ollama on your laptop, if you'd rather run extraction by hand
- Fallback with no LLM: regex for common date formats, with every hit flagged for review

At about 40 races, roughly 2–5 pages change on a typical day, so a free tier is plenty.

**Pages that are hard to read**

- *JavaScript-only sites:* use Playwright in GitHub Actions (free, but slower), and only for the races that need it.
- *Dates only on social media or in emails:* don't scrape these. Mark the race `manual` and rely on community submissions.
- *PDF entry packs:* extract the text with `pypdf`, then use the same LLM step.

**Evaluation.** Keep a test set of 20–30 saved pages with known correct dates. Run extraction against it in CI whenever the prompt or model changes, and track accuracy per field. This is also the strongest portfolio piece in the project.

**Community input.** A Google Form (name of race, link, what changed) feeds a Google Sheet. A weekly job reads the sheet with the Sheets API and opens a PR for each new row, through the same validation and review.

## Website, calendar and reminders

Members get reminders by subscribing to a calendar feed once. There are no accounts and no stored personal data.

**Website (static).** Built from `races.yaml` on every merge. Astro or Eleventy both work; a single page with a little vanilla JS is also enough.

- “Upcoming deadlines” at the top: ballots opening or closing in the next 30 days
- Full race table with filters for distance, month and entry type
- Each race shows its status, a “last verified” date and a link to the official page
- A “Suggest a race / report a change” link to the Google Form
- Calendar subscribe buttons (Google, Apple, Outlook) with one-line instructions

**Calendar feeds (.ics).** Generated with the Python `ics` or `icalendar` library and published alongside the site.

- `all.ics`, plus `marathons.ics`, `halves.ics` and `ballots-only.ics`
- Every entry window creates events for “Ballot opens”, “Ballot closes in 2 days” and “Ballot closes today”. Each event links to the entry page.
- Race days are all-day events.
- Stable event UIDs (e.g. `london-marathon-2027-ballot-opens`), so an updated date moves the existing event instead of duplicating it.

Two gotchas. Google Calendar ignores alarms in subscribed feeds, which is why the reminder is its own event (“closes in 2 days”) instead of an alert. Google also refreshes subscribed feeds slowly, sometimes taking a day, so announce last-minute changes in the group too.

**Email digest (optional, Phase 3).** A weekly “this week in ballots” email, built from the same data. Free options: Buttondown or Resend free tiers (check current limits). Use double opt-in and include an unsubscribe link.

**WhatsApp distribution.** Don't put a bot in the group. Unofficial libraries (whatsapp-web.js, Baileys) break WhatsApp's terms and can get the number banned. The official Business API needs a business number and charges per message.

- Pin the site and calendar link in the group description
- The pipeline also writes `digest.txt`, a ready-to-paste weekly WhatsApp message with emoji-free plain text and links. A club admin pastes it on Mondays.
- If the club later wants push alerts, a Telegram channel and bot are free and allowed.

## Plan A: solo build

Working alone at about 6–8 hours a week, the club has a usable calendar in week 2 and full automation by week 6. Each phase ships something people can use, so the project is worth having even if it stops early.

**Phase 1 — Manual MVP (weeks 1–2)**

- [x] Create the GitHub repo (public, MIT licence) with `races.yaml`, a schema and a README
- [ ] Ask the WhatsApp group which races to include; agree the first 30–40
- [ ] Fill in each race by hand from its official page, with `source_url` and `confidence`
- [x] Write `build.py`: validates the YAML and generates the `.ics` feeds and a static page
- [x] GitHub Action: run `build.py` on every push and deploy to GitHub Pages
- [ ] Share the link and subscribe instructions in the group; pin it

*Done when:* 10 members have subscribed and the deadlines on the page match the official sites.

**Phase 2 — Change detection (weeks 3–4)**

- [ ] Fetch-and-clean script with robots.txt checks and polite rate limiting
- [ ] Hash store and a daily scheduled GitHub Action
- [ ] When a page changes, open a GitHub issue with a link and a text diff (no LLM yet)
- [ ] Google Form + Sheet for community submissions

*Done when:* a real ballot announcement is caught within 24 hours.

**Phase 3 — LLM extraction and polish (weeks 5–6)**

- [ ] Extraction prompt, JSON schema and Pydantic validation
- [ ] Bot opens PRs with proposed field changes and quoted evidence
- [ ] Evaluation set of 20–30 saved pages, run in CI
- [ ] Filters, “upcoming deadlines” panel and `digest.txt` for WhatsApp
- [ ] Optional: weekly email digest

*Done when:* most changes arrive as ready-to-merge PRs and review takes under 30 minutes a week.

**Phase 4 — Ongoing (from week 7)**

- [ ] Review bot PRs (busiest Sep–Jan, when most ballots run)
- [ ] Roll each race into next year's edition once results are out
- [ ] Add a co-maintainer from the club, so the project doesn't depend on one person

**Risks of going solo:** you are the only reviewer, so a busy fortnight means stale data. Mitigate by recruiting one club member as a non-technical reviewer who can approve PRs in the GitHub web UI.

## Plan B: two engineers

With two engineers at the same 6–8 hours a week each, v1 lands in about 4 weeks instead of 6. The bigger gain is resilience: two reviewers means data stays fresh during a busy month.

Split the work along the one seam in the system, `races.yaml`. Engineer 1 owns everything that writes to it; Engineer 2 owns everything that reads from it.

| Week | Engineer 1 — data and pipeline | Engineer 2 — site and delivery |
| --- | --- | --- |
| 1 | Schema (shared), seed data | `build.py`, calendar feeds |
| 2 | Fetch, clean, hash, daily Action | Static site, GitHub Pages deploy |
| 3 | LLM extraction, validation | Google Form + Sheets job, WhatsApp digest |
| 4 | PR bot, evaluation set, monitoring | Email digest, contributor docs |

Both lanes start in week 1 because the schema is agreed on day one; after that, neither engineer blocks the other.

**Engineer 1 — data and pipeline (suggested: you).** Schema, seed data, fetch/clean/hash, LLM extraction, validation, the PR bot, the evaluation set and monitoring. This lane is the AI engineering showcase.

**Engineer 2 — site and delivery.** `build.py`, calendar feeds, the static site, the Google Form and Sheets job, the WhatsApp digest, the email digest and docs for contributors.

**Shared**

- Day 1: agree the `races.yaml` schema and commit a JSON Schema file. It's the contract between the two lanes.
- Both review the other's PRs; both approve data PRs.
- A 20-minute check-in each week, plus a GitHub Project board (free) with columns To do / Doing / Review / Done.
- Branch protection on `main`: one approving review required, CI must pass.

**Ongoing split (after v1):** alternate weeks as the data reviewer during ballot season (Sep–Jan). Each person then spends about 15 minutes a week on reviews.

**Watch out for:** schema changes made by one person without the other. Any change to the schema file needs both approvals.

## Costs, risks and open questions

The whole project runs at £0 a month. The only optional cost is a custom domain at about £10 a year; the free `username.github.io` address works fine.

**Free-tier limits to watch** (check current terms before building):

- *GitHub Actions:* free for public repos on standard runners. A private repo gets a monthly minute allowance, which a daily job uses only a small part of.
- *GitHub Pages:* 1 GB site size and a soft limit of 100 GB bandwidth a month, far more than a club needs.
- *LLM free tiers:* rate limits and models change. Keep the extraction step behind one small function so you can swap providers.
- *Email tiers:* subscriber or daily-send caps. Calendar feeds have no such limit, which is one more reason to make them the main channel.

**Risks**

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Wrong ballot date published | Members miss a ballot | Human review on every change; quoted evidence; “last verified” shown; official link on every entry |
| Race site redesign breaks extraction | Silent stale data | Alert when a page fails to fetch or extraction returns nothing for 7 days |
| Maintainer burnout | Project stops | Co-maintainer; under 30 min a week target; keep scope to about 40 races |
| Site blocks the bot | No updates for that race | Mark as `manual`; rely on community submissions |
| Free tier withdrawn | Pipeline step stops | Provider-agnostic code; regex fallback; GitHub alternatives (Cloudflare Pages, GitLab CI) |

**Legal and privacy**

- Monitor official race pages only. Aggregators such as Let's Do This and Finishers usually forbid scraping in their terms.
- Respect robots.txt, keep to one request per page a day and identify the bot.
- Store facts (dates, prices) and link to the source. Don't copy race descriptions, logos or photos.
- Calendar feeds collect no personal data. If you add email, GDPR applies: get explicit consent, use double opt-in, provide an unsubscribe link and a short privacy note, and store only email addresses.
- Add a disclaimer: “Always confirm dates on the official site. Not affiliated with any race.”

**Open questions**

- [x] Which races go on the first list? (Ask the group.) First suggestions added Oct 2026.
- [x] Include international majors from day one, or later? From day one: Paris, Berlin Half and Milan.
- [ ] Who besides you can approve PRs?
- [ ] Public repo (free Actions, open to contributors) or private?
- [ ] Is a weekly WhatsApp digest wanted, and who posts it?
- [ ] Should the project carry the club's name, or stay independent?
