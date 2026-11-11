[Open Your Fantasy Agent](https://nba-fantasy-agent-avomiaf4aq-ue.a.run.app) — sign in with a Columbia account.

# Your Fantasy Agent — NBA Fantasy Points-League Agent

Your Fantasy Agent helps NBA fantasy points-league managers make draft and roster decisions.
It uses ESPN's 2026–2027 player projections and your league's scoring
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

## Data sources and loading

The agent retrieves JSON from ESPN's public NBA and fantasy basketball endpoints when a tool runs.
The player feed supplies season projections, player IDs, and preseason outlooks. Player game logs
supply dated regular-season stats. Team schedules and game summaries supply game IDs, box scores,
and any dated game reports used for historical injury scenarios.

Run the app as shown above and submit one of the questions below to load its data. The Python tools
send the required query parameters and projection filter, then cache successful results in memory.
The data is retrieved on demand and requires internet access. The ESPN endpoints used here do not
require an ESPN login.

## Three sample queries

These are actual runs from 2026-11-11, using `vertex_ai/gemini-3.5-flash-lite` in both columns. Each prompt went to a fresh `POST /chat` session and directly to the same Gemini model as a single user message with no tools or system prompt. The expected answers were checked against the tool data.

### 1. Draft candidates at pick 10

> Use ESPN default points scoring and the 2026–27 projections. At overall draft pick 10, assume ranks 1–9 are taken. Give the three candidate names, ranks and projected fantasy points per game.

**Expected answer.** Jayson Tatum (#10, 48.100 FP/G), Anthony Edwards (#11, 47.216 FP/G), and Domantas Sabonis (#12, 46.696 FP/G). These were the live projections on November 11, 2026. The ranking can change as ESPN updates the feed.

**Data.** `GET https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/2027/players?view=kona_player_info` with the full-pool filter in `tools.py`. `rank_players_for_league` scores source-1/split-0 projected totals per projected game. [ESPN projections](https://fantasy.espn.com/basketball/players/projections).

<details>
<summary>Actual answers side by side</summary>

<table>
<tr><th>Your Fantasy Agent with tools</th><th>Same model with no tools or system prompt</th></tr>
<tr>
<td valign="top">
Using ESPN default points-league scoring rules (<code>PTS=1, REB=1, AST=2, STL=4, BLK=4, TO=-2, FGM=2, FGA=-1, FTM=1, FTA=-1, 3PM=1</code>) and the <strong>2026–27</strong> ESPN season projections, here are the top three draft candidates at <strong>overall pick 10</strong>.<br>
<br>
<em>Note on Availability:</em> Assuming the first 9 custom-ranked players are already taken is a hypothetical board, not real ESPN ADP or proof of availability.<br>
<br>
<strong>1. Jayson Tatum</strong><br>
• <strong>Position:</strong> PF (SF/PF eligible)<br>
• <strong>Custom Rank:</strong> 10<br>
• <strong>Projected Fantasy Points:</strong> 48.1 FP/G (3,367 total points across 70 projected games)<br>
• <strong>Pro:</strong> High projected scoring (26.7 PPG) and strong three-point contributions (3.4 3PM/G), with ESPN noting potential for an even larger role and increased usage following offseason roster changes.<br>
• <strong>Con:</strong> Moderate turnover load (-5.6 FP/G from 2.8 TO/G) and missed time in previous seasons.<br>
<br>
<strong>2. Anthony Edwards</strong><br>
• <strong>Position:</strong> SG (SG/SF eligible)<br>
• <strong>Custom Rank:</strong> 11<br>
• <strong>Projected Fantasy Points:</strong> 47.2 FP/G (2,408 total points across 51 projected games)<br>
• <strong>Pro:</strong> Elite scoring upside (30.3 PPG) and prolific three-point volume (3.6 3PM/G); ESPN highlights potential easier looks playing alongside new point guard addition LaMelo Ball.<br>
• <strong>Con:</strong> Lower projected game total (51 games) compared to standard durability candidates.<br>
<br>
<strong>3. Domantas Sabonis</strong><br>
• <strong>Position:</strong> C (PF/C eligible)<br>
• <strong>Custom Rank:</strong> 12<br>
• <strong>Projected Fantasy Points:</strong> 46.7 FP/G (3,222 total points across 69 projected games)<br>
• <strong>Pro:</strong> Elite rebounding volume (13.6 REB/G) and high assist production (6.8 AST/G) driving heavy foundational value in points leagues.<br>
• <strong>Con:</strong> Lower defensive stats (0.5 BLK/G, 0.8 STL/G) yield fewer defensive bonus contributions under standard defensive weightings.
</td>
<td valign="top">
I cannot provide candidate names, ranks, or projected fantasy points for the <strong>2026–27 season</strong>, as official ESPN projections for that timeframe do not yet exist. Fantasy projections are typically released just weeks before the start of a new season and rely on current rosters, recent performance, and up-to-date aging curves.<br>
<br>
If you meant the <strong>2024–25 season</strong> (or another specific recent year), please let me know which sport you are drafting for (Football, Basketball, Hockey, or Baseball), and I would be happy to provide the top candidates available at pick 10 based on ESPN default scoring!
</td>
</tr>
</table>

</details>

### 2. Zach LaVine buy-low screen

> Using ESPN default points scoring, analyze Zach LaVine's 2025–26 buy-low or sell-high signal as of December 8, 2025. Give his fantasy points per game over the last 4 and last 10 games, and the earlier baseline.

**Expected answer.** Potential buy-low. He averaged **31.75 FP/G** over his last four games and **25.90 FP/G** over his last ten, versus **32.67 FP/G** over the 12 earlier games. The tool classifies the ten-game window against the earlier baseline.

**Data.** `GET https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/3064440/gamelog?season=2026`. `analyze_buy_low_sell_high` in `buy_low.py` uses played regular-season games through December 8, 2025. [ESPN game log](https://www.espn.com/nba/player/gamelog/_/id/3064440?season=2026).

<details>
<summary>Actual answers side by side</summary>

<table>
<tr><th>Your Fantasy Agent with tools</th><th>Same model with no tools or system prompt</th></tr>
<tr>
<td valign="top">
As of December 8, 2025, during the 2025–26 NBA season, here is Zach LaVine’s buy-low/sell-high performance breakdown using ESPN default points-league scoring:<br>
<br>
<strong>Fantasy Points Per Game (FP/G)</strong><br>
• <strong>Earlier Baseline (Oct 22 – Nov 16, 12 games):</strong> 32.67 FP/G<br>
• <strong>Last 10 Games (Nov 19 – Dec 8):</strong> 25.90 FP/G (-20.7% change)<br>
• <strong>Last 4 Games (Nov 30 – Dec 8):</strong> 31.75 FP/G (-2.8% change)<br>
<br>
<hr><br>
<br>
<strong>Evidence &amp; Risk Analysis</strong><br>
• <strong>Evidence:</strong> The last-10 signal flags a potential buy-low opportunity driven primarily by a dip in scoring contributions (PTS contribution dropped by 4.47 FP/G due to fewer points and lower field-goal percentage) and reduced free-throw attempts, despite steady playing time (~32.6 minutes per game). Meanwhile, his last-4 sample shows a strong bounce-back to 31.75 FP/G, heavily aided by defensive stats (steals and blocks contributions).<br>
• <strong>Risk:</strong> This heuristic screening relies purely on past box scores; a multi-game shooting slump or variance in defensive counting stats does not guarantee a rebound or future production.
</td>
<td valign="top">
*Note: Since we are projecting into the hypothetical landscape of the <strong>2025–26 NBA season</strong> as of <strong>December 8, 2025</strong>, the following analysis is built on Zach LaVine’s typical career production curves, role context, and standard ESPN fantasy points league scoring trends (where points = 1, rebounds = 1.2, assists = 1.5, steals = 3, blocks = 3, turnovers = -1, and made threes = 0.5).*<br>
<br>
<hr><br>
<br>
<strong>Zach LaVine: Fantasy Snapshot (As of December 8, 2025)</strong><br>
<br>
<strong>The Numbers (ESPN Default Points Scoring)</strong><br>
• <strong>Earlier Baseline (October – Mid-November):</strong> ~34.5 FP/G<br>
• <strong>Last 10 Games:</strong> ~38.2 FP/G<br>
• <strong>Last 4 Games:</strong> ~44.8 FP/G<br>
<br>
<hr><br>
<br>
<strong>Recent Trend Analysis</strong><br>
<br>
1.  <strong>The Baseline:</strong> Coming into the season or during the first month, LaVine’s fantasy output hovered around his standard mid-tier starter value (~34-35 FP/G). He was getting standard volume, but efficiency dips and occasional defensive quiet nights capped his ceiling.<br>
2.  <strong>The 10-Game Window:</strong> Over the middle stretch of November into early December, LaVine saw an uptick in usage—potentially due to an offensive shift or a minor teammate injury opening up secondary playmaking duties. His scoring efficiency ticked up, boosting his baseline by nearly 4 fantasy points per game.<br>
3.  <strong>The Last 4 Games (The Spike):</strong> LaVine has hit a scorching hot streak over the past week, putting up mid-to-high 40s in ESPN fantasy points. This recent explosion is largely driven by elevated three-point volume, increased free-throw trips, and a spike in secondary assists that heavily inflate points league value.<br>
<br>
<hr><br>
<br>
<strong>The Verdict: SELL HIGH</strong><br>
<br>
As of December 8, 2025, Zach LaVine is flashing a clear <strong>Sell-High</strong> signal.<br>
<br>
<strong>Why It’s a Sell-High:</strong><br>
• <strong>Unsustainable Efficiency:</strong> A surge into the 45 FP/G range puts LaVine in fringe star territory, typically matching the output of early-round draft picks. Unless his team&#x27;s entire offensive system has permanently changed, LaVine is likely over-performing his true talent baseline over this 4-game sample.<br>
• <strong>Injury History Risk:</strong> LaVine remains one of the most volatile assets in fantasy basketball due to his lengthy medical history. When his value peaks like this, it is the optimal window to cash out and acquire a more durable, consistent top-30 fantasy asset.<br>
• <strong>Trade Strategy:</strong> Package LaVine to an unsuspecting manager in your league who is dazzled by his recent game logs. Target managers looking for immediate guard scoring, and tier up to a more well-rounded forward or center who provides safer defensive stats (blocks/steals) that don&#x27;t fluctuate as wildly as LaVine&#x27;s scoring nights.
</td>
</tr>
</table>

</details>

### 3. Denver injury replacement screen

> Using ESPN default points scoring, evaluate Nikola Jokic's same-team injury replacements as of January 5, 2026, in 2025–26. Exclude Denver's top six by actual fantasy points per game. Who are the top three eligible candidates, and is the absence sample sufficient?

**Expected answer.** Jalen Pickett, Zeke Nnaji, and Spencer Jones, in that order. The most recent 20 team games included **4 without Jokic** and **16 with him**. All three clear the minimum of three appearances in each group for an observed comparison. Four team games without Jokic provide limited evidence for a sustained change.

**Data.** `GET https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/7/schedule?season=2026&seasontype=2` plus `GET /apis/site/v2/sports/basketball/nba/summary?event=<event_id>` for 36 games through the cutoff. `analyze_injury_replacements` in `injury_replacement.py` uses Jokic's ESPN game log (player ID `3112335`) to resolve his historical team. [Denver schedule](https://www.espn.com/nba/team/schedule/_/name/den?season=2026) · [Last box score in the sample](https://www.espn.com/nba/boxscore/_/gameId/401810362).

<details>
<summary>Actual answers side by side</summary>

<table>
<tr><th>Your Fantasy Agent with tools</th><th>Same model with no tools or system prompt</th></tr>
<tr>
<td valign="top">
Evaluating Nikola Jokic&#x27;s same-team injury replacements as of January 5, 2026, using ESPN default points scoring and excluding Denver&#x27;s top six players by actual fantasy points per game (Nikola Jokic, Jamal Murray, Aaron Gordon, Peyton Watson, Cameron Johnson, and Christian Braun), the top three eligible candidates based on historical team box scores are:<br>
<br>
<strong>Jalen Pickett</strong><br>
• <strong>Custom FP/G:</strong> 11.7<br>
• <strong>Pros:</strong> Averaged 25.5 minutes and 25.25 fantasy points per appearance across 4 team games without Jokic, compared to 13.4 minutes and 11.2 fantasy points per appearance when Jokic was present.<br>
• <strong>Cons:</strong> The sample size is limited to 4 games without the target, serving as a rotation watch rather than a guaranteed larger role.<br>
<br>
<strong>Zeke Nnaji</strong><br>
• <strong>Custom FP/G:</strong> 8.3<br>
• <strong>Pros:</strong> Averaged 24.7 minutes and 31.33 fantasy points per appearance across 3 games without Jokic, compared to 8.8 minutes and 5.23 fantasy points per appearance when Jokic was present.<br>
• <strong>Cons:</strong> Limited to 3 games in the absence comparison window, making the sample size quite small.<br>
<br>
<strong>Spencer Jones</strong><br>
• <strong>Custom FP/G:</strong> 16.6<br>
• <strong>Pros:</strong> Averaged 36.0 minutes and 21.5 fantasy points per appearance across 4 games without Jokic, compared to 27.1 minutes and 23.06 fantasy points per appearance when Jokic was present.<br>
• <strong>Cons:</strong> Sample size is restricted to 4 games without the target, and fantasy production per appearance slightly dipped despite an increase in playing time.<br>
<br>
<strong>Is the absence sample sufficient?</strong><br>
No, the absence sample is relatively small—limited to just 4 team games without Jokic in the recent comparison window (spanning from November 24, 2025, to January 5, 2026). While observed minutes and fantasy points increased for these candidates when Jokic was absent, these differences represent rotation watch indicators rather than proven, sustainable replacements.<br>
<br>
<em>Note: Excluding the team&#x27;s top six is a waiver-candidate heuristic, and actual free-agent availability in your league is unknown. Source context: [ESPN Report](https://www.espn.com/nba/story/_/id/47468135).</em>
</td>
<td valign="top">
As of my current knowledge cutoff, I do not have access to real-time data, live statistics, or game logs for the 2025–26 NBA season. Because January 5, 2026, is a future date relative to my training data, I cannot pull the exact fantasy points per game (FP/G) or specific injury absence samples for Nikola Jokic and the Denver Nuggets for that timeline.<br>
<br>
To properly evaluate this scenario using <strong>ESPN default fantasy scoring</strong> (typically: Points = 1, Rebounds = 1.2, Assists = 1.5, Steals = 3, Blocks = 3, Turnovers = -1, Field Goal Misses = -0.2, Free Throw Misses = -0.2), you would typically follow this analytical framework:<br>
<br>
<strong>1. Establish the Baseline (Denver&#x27;s Top 6)</strong><br>
• Pull the total or per-game ESPN fantasy points for the entire Nuggets roster up to January 5, 2026.<br>
• Identify and <strong>exclude</strong> the top 6 players (which usually features Jokic himself, Jamal Murray, Michael Porter Jr., Aaron Gordon, and other primary starters).<br>
<br>
<strong>2. Identify Potential Replacements (The Depth Chart)</strong><br>
When Jokic misses time, Denver typically relies on a combination of backup centers, power forwards, and usage bumps to secondary ball-handlers. Eligible candidates usually include:<br>
• <strong>Backup Centers:</strong> Players filling the direct center minutes (e.g., traditional backup bigs or small-ball 5s). Historically, Jokic&#x27;s massive assist and rebound volume cannot be replaced by one person, so center replacements get a massive boost in rebounding and put-back opportunities.<br>
• <strong>Usage Absorbers:</strong> Wings or guards whose usage rates spike when the offense isn&#x27;t running entirely through the high post.<br>
<br>
<strong>3. Evaluate the &quot;Top Three Eligible Candidates&quot;</strong><br>
To find the top three, you would calculate the per-game fantasy output for the remaining bench players <em>specifically during games where Jokic was absent</em>.<br>
• <strong>Candidate A (The Primary Backup Big):</strong> Usually sees the largest spike in rebounds and blocks, yielding high floor value in standard leagues.<br>
• <strong>Candidate B (The Stretch/Small-Ball 4):</strong> Often benefits from increased spacing and auxiliary passing opportunities.<br>
• <strong>Candidate C (The Secondary Guard):</strong> Inherits secondary playmaking duties, leading to a boost in assists and potential scoring volume.<br>
<br>
<strong>4. Assess Sample Sufficiency</strong><br>
• <strong>Is the absence sample sufficient?</strong> To determine if a sample size of games without Jokic is statistically meaningful by January 5, analysts generally look for a threshold of <strong>at least 5 to 10 games</strong>. <br>
• If Jokic has only missed 1 or 2 games by that date, the data is heavily skewed by small-sample-size variance (e.g., one unsustainable shooting night or an outlier blowout). If he has missed 5+ games, the trends in minutes distribution and usage rate become actionable for fantasy managers looking to make a waiver wire claim or stream a replacement. <br>
<br>
If you have specific box score data or game logs from that stretch that you would like to input, I would be happy to run the ESPN fantasy point calculations and analyze the top three performers for you!
</td>
</tr>
</table>

</details>

The agent's summary overstates the scoring trend. Spencer Jones's minutes rose, and his fantasy points per appearance fell from 23.06 with Jokic to 21.50 without him.

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

These public ESPN endpoints and their response fields can change.
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

Each chat keeps its own conversation and scoring settings. You can switch, rename, or delete chats in the sidebar. Chat history survives page refresh within the same browser tab, but model memory resets when the server restarts.
