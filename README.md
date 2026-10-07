[Open Your Fantasy Agent](https://nba-fantasy-agent-avomiaf4aq-ue.a.run.app) — sign in with a Columbia account.

# Your Fantasy Agent — NBA Fantasy Points-League Agent

Your Fantasy Agent uses ESPN's 2026–2027 player projections and your league's scoring
weights to rank projected fantasy points **per game**. Ask for an overall pick
and it returns three draft candidates with custom ranks, per-game scores, and
the statistics driving their value. Gemini chooses the tool and explains the
result; Python performs the arithmetic and candidate selection.

## Run locally

```bash
uv sync
gcloud auth application-default login
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID uv run app.py
```

Open http://localhost:8080. If port 8080 is occupied, stop the previous server
or set `PORT=8081`. Model and region can be overridden with `GEMINI_MODEL` and
`VERTEX_LOCATION`; the defaults match the original `main.py` setup test.
`VERTEX_PROJECT` is also accepted as a fallback to `GOOGLE_CLOUD_PROJECT`.

Edit the scoring fields and press **Confirm Changes**, then ask for
rankings or draft advice in chat. You can also give weights directly in chat. The preset uses **ESPN default points scoring**: PTS=1, REB=1, AST=2,
STL=4, BLK=4, TO=-2, FGM=2, FGA=-1, FTM=1, FTA=-1, 3PM=1.
[ESPN scoring reference](https://www.espn.ph/fantasy/basketball/story/_/id/20800285/adjusting-settings). Rules supplied in chat are remembered in that session. Confirmed UI rules are sent with your next chat question and remembered by the
agent. Unconfirmed edits have no effect. Later chat instructions can update
scoring without the UI overwriting them; confirm the UI again to replace rules.
Confirmed settings survive refresh within the browser session.

## Three grader sample queries

1. "Use ESPN default points scoring and 2026–2027 projections. Who should I
   draft at overall pick 10?" Then, in the same chat, ask "Change STL to 10;
   keep the other weights. Show ranks 10–15." This checks remembered rules.
2. "Use ESPN default points scoring. Analyze Zach LaVine for Buy-Low or
   Sell-High in the 2025–26 season, as of 2025-12-08. Compare his last 4 and
   10 games with his earlier baseline." Inspect the interactive chart and traces.
3. "Using ESPN default points scoring, analyze Nikola Jokic’s same-team injury
   replacements as of 2026-01-05 in 2025–26. Exclude the team’s top six by
   fantasy points per game." This historical analysis can take longer because it
   fetches and validates the team's individual game box scores.


## Tools

`rank_players_for_league(scoring_weights, season=2027, overall_pick=None,
drafted_players=None, top_n=20)`:

- Retrieves ESPN's public projection JSON with an explicit player-pool filter;
  a plain unfiltered request only returns a default subset. ESPN season 2027
  represents the season ending in 2027 (2026–2027).
- Supports PTS, REB, AST, STL, BLK, TO, FGM, FGA, FTM, FTA, 3PM, 3PA, FGMI,
  FTMI, and 3PMI. Omitted metrics are zero; penalties use negative weights.
  Unsupported metrics are rejected rather than silently ignored.
- Uses **projected season counting-stat totals** in the source-1 / split-0
  block. Computes `sum(stat_total * weight) / projected_GP` once. The ESPN
  Sortable/Full Projections website shows rounded per-game values; these must
  NOT be divided by games again. Calculating from unrounded season totals
  can differ slightly from manually multiplying rounded website values.
- Ranks on unrounded per-game points. Reports projected games and weighted
  contributions. Players missing GP or any scored metric are excluded and
  counted; missing statistics are never treated as zero.
- `overall_pick` returns exactly three candidates. Without `drafted_players`,
  assumes the first pick-minus-one players in **our custom ranking** are gone.
  This is a hypothetical scenario, not ADP or a real availability forecast.
- With an actual drafted list, excludes only those names, regardless of pick.
  Accent and punctuation differences are normalized; unresolved names return
  an actionable error. A partial-list warning is emitted when count differs
  from pick-minus-one. No injury or positional-scarcity optimization is implied.
- Handles invalid scoring, unsupported categories/bonuses, unknown player
  names, insufficient candidates, HTTP errors, timeouts, missing projections,
  and invalid feed data with `ok`, `error`, `message`, `next_step`, `retryable`.
- Caches successful ESPN data for 15 minutes per process; responses report
  source, fetch time, and cache hit status. No stale/fake fallback is used.

`get_player_outlooks(player_ids, season=2027)` reads ESPN's `seasonOutlook`
field for up to ten ESPN player IDs. After selecting three draft candidates,
the agent calls this tool to add one short Pros line and one short Cons line
per candidate. Commentary is briefly paraphrased and attributed to ESPN.
Missing players/outlooks are reported, not invented. The tool shares the
projection feed's cache and external-data error handling. These are season
outlooks, not live transaction news; the feed supplies no publication timestamp.
Roster effects are discussed only when supported in the outlook, and never
change calculated scores or ranking order. Both tool calls appear in `/chat`
traces and the existing expandable UI; no new buttons are added.

`analyze_buy_low_sell_high(player_name, scoring_weights, as_of_date=None, season=None)`
fetches actual ESPN game logs. Omitted cutoff uses today in America/New_York;
omitted season follows the cutoff using a July–June season convention. Explicit
historical dates still work. Ending year 2026 is 2025–26; no multi-year history
is needed. Current requests never fall back to previous-season results when the
new regular season has no data or insufficient appearances. Only played regular-season games dated on/before the cutoff
in America/New_York are used. Preseason, playoffs, zero-minute DNPs and later
performances are excluded. Full-season data resolves player identity only;
projections/outlooks are never used as historical performance or news evidence.

- Requires 20 appearances: last 10 plus at least 10 earlier baseline games.
- Reports last 4, last 10, disjoint baseline before last 10, season-to-date,
  date ranges, custom FP/G, minutes, attempts, turnovers and shooting percentages.
- Shooting percentages use total makes/attempts, not averages of game percentages.
- Potential Buy-Low: last-10 FP/G down at least 15%, minutes and FGA down no more
  than 10%, and FG% down at least 5 percentage points versus earlier baseline.
- Potential Sell-High: FP/G up at least 15%, minutes/FGA each within 10% of
  baseline, and FG% up at least 5 percentage points. Opportunity declines and
  other changes receive distinct signals; last-4 changes alone do not classify.
- Thresholds are transparent, unvalidated heuristics; no rebound probability,
  confirmed temporary slump, usage rate, injury news or trade offer is invented.
- Historical news is not connected. The tool explicitly returns that limitation.
  A future news integration must enforce publication dates at/before the cutoff.
- Responses retain visible name/args/result tool traces. No new UI buttons.
- The frontend draws an interactive SVG trend chart from returned `game_history`:
  actual game FP, trailing 4- and 10-game averages, and the disjoint earlier
  baseline. Only at/before-cutoff games are returned. Rolling averages start
  once a full window exists. Hover/tap or arrow keys inspect dated points.
  Charts restore with session history and need no external chart service/CDN.

The endpoint is a public ESPN feed, not a supported API contract. Local access
is tested; Cloud Run access and future schema stability still require checking.
References: [ESPN projections](https://fantasy.espn.com/basketball/players/projections),
[ESPN field mapping reference](https://github.com/cwendt94/espn-api/blob/master/espn_api/basketball/constant.py),
[LiteLLM tool-calling protocol](https://docs.litellm.ai/docs/completion/function_call).

## Chat response and session memory

`POST /chat` accepts `message`, optional `session_id`, and optional `scoring_weights`
when the user confirms UI changes. Validated rules accompany the model’s input;
the displayed user message stays unchanged. Every response retains:

```json
{
  "response": "Assistant answer",
  "session_id": "random-session-id",
  "tool_calls": [
    {"name": "rank_players_for_league", "args": {}, "result": {}}
  ]
}
```

Every requested call, including validation failures, is recorded with actual
arguments and results, and every result is sent back to Gemini. The interface
displays expandable tool details. Tool traces survive page refresh through
`GET /sessions/<session_id>`. Raw assistant/tool protocol messages remain in
model history; the UI renders user messages and final answers separately.
If a later Gemini call fails, completed tool traces are returned, but partial
conversation history is not committed. Tool rounds are bounded.

Each session has separate server memory and its own request lock. The browser
stores the session ID in sessionStorage. A new tab usually starts fresh;
duplicating a tab may copy its ID, so use **New chat** for an independent chat.
The session ID acts as access to its history. Histories clear on server restart.
Local limits are 100 turns per session and 1,000 sessions per process. Shared
storage such as Firestore is required before using multiple Cloud Run instances.

## Checks

```bash
uv run python -m unittest discover -s tests -v
```

Tests use fixture data and a mocked model to verify calculation, scoring changes,
actual vs hypothetical availability, missing-data handling, API errors, tool
round trips, provider metadata, visible traces, session isolation, and rollback.

## Cloud Run deployment

The root `Dockerfile` installs dependencies from `uv.lock` and runs Gunicorn.
One worker and a maximum of one Cloud Run instance keep the current in-memory
session implementation consistent across requests. Sessions remain separate;
server restarts, new revisions, or scaling to zero clear them. Shared persistent
storage is required for durable memory or multiple instances. Deployment uses Identity-Aware Proxy (IAP), restricted to `columbia.edu` accounts; the runtime service account needs `roles/aiplatform.user`.
No local Google credentials or API keys are included in the container.
This application is Flask (WSGI); use the included Dockerfile/Gunicorn entrypoint,
or a buildpack with `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 600 app:app`.
The course guide’s Uvicorn entrypoint is for ASGI applications and does not fit Flask directly.

`cloudbuild.yaml` builds, pushes, and deploys the service. Connect this GitHub
repository using Developer Connect and create a push trigger matching `^main$`, using
`cloudbuild.yaml`. Default settings are `us-east1`, Artifact Registry repository
`nba-agent`, and Cloud Run service `nba-fantasy-agent`. The runtime service
account is `nba-fantasy-agent@PROJECT_ID.iam.gserviceaccount.com`. Configure the
build service account with the permissions needed to write images, deploy Cloud
Run, and act as this runtime account. See
[Google's continuous-deployment instructions](https://docs.cloud.google.com/run/docs/continuous-deployment).

Before submission, `submission.json` must contain the deployed URL and every
team member's UNI/email. Keep the service available until grades are released.
Private repositories must invite the grader accounts listed in the assignment.
The original `main.py` Gemini connection test is retained.

## Historical injury replacements

`analyze_injury_replacements(injured_player, scoring_weights, as_of_date=None,
season=2026)` supports last season (2025–26). For an injury episode, specify its
historical date, e.g. "Using ESPN default points scoring, analyze Nikola Jokic’s
same-team injury replacements as of 2026-01-05 in 2025–26. Exclude the team’s top
six by fantasy points per game."

The tool resolves historical team identity from the player's actual latest
pre-cutoff appearance, filters completed regular-season schedule events by their
own season/date fields, and parses every pre-cutoff team box score. No incomplete
season is silently used. It computes actual custom FP/G and excludes the top six
team-season participants. Candidate membership comes from the latest dated game
roster; this is not a complete historical roster or a league-specific FA list.
Past team participants can affect the top-six ranking; trades remain a limitation.

Minutes with/without the target are compared over the last 20 team games. A
comparison requires at least three candidate appearances in each group; weaker
samples are labeled rotation watch only. Target absence is not proof of injury.
Available game recaps are filtered by publication and modification dates and
linked as evidence; no current news or future performances enter the result.
Concurrent injuries, opponents, overtime and role changes can confound differences.
No increased-minute projection or return date is invented. If no historical cutoff
is given for a season-wide retrospective screen, the tool uses June 30, 2026,
clearly marked as historical. No new buttons are added; tool calls remain visible.

## Current hypothetical injury scenarios

`analyze_current_injury_scenario(injured_player, scoring_weights, season=2027,
available_players=None)` verifies the current roster's season and target membership,
then excludes the six highest custom projected FP/G teammates and the target.
It returns up to three projected candidates, prioritizing positional eligibility;
unrelated positions are excluded rather than used to fill three names,
with optional 2025–26 same-team per-appearance comparisons from actual game logs.
At least three played appearances in each group are needed for a minutes delta.
Other-team performances are excluded. Historical absence is not proof of injury.
Missing history is reported without blocking the current hypothetical screen.

Try: "What if Jokic is injured in 2026–27? Using my confirmed scoring, who should
I watch for an FA replacement?" Supply `available_players` through chat to limit
choices to your actual FA list. This is a same-team watch list, not a complete
league-wide waiver recommendation or verified depth chart. Current-out players
are excluded; other reported injury snapshots remain visible as risks. Players
without complete projections may appear as watch-only candidates when position
fit and at least three historical appearances in each comparison group support
consideration. Their projected FP/G and rank remain null; the top-six exclusion
covers only projected roster members. Injury guidance uses unnumbered names and
short Pros/Cons rather than a displayed ranking. Original projections are not
adjusted upward for an injury. No coach/news report feed is integrated in this
mode; rotation claims, return dates and future minute gains are not invented.

## Chat workspace

New chat creates a separate conversation in the sidebar (a horizontal tab strip
on mobile). Existing chats remain available to switch back to, with their own
session ID, confirmed scoring, draft text, messages, tool traces and charts.
New chats inherit the current confirmed scoring but have independent model memory.
Titles use the first user message. Tabs and displayed history are saved in this
browser tab's sessionStorage and survive refresh, but are not a permanent account
archive. After a server restart, saved messages remain visible while the app
clearly reports that model memory has ended and the next message starts a fresh
session. Switching chats is disabled during a request to avoid mixing responses.
