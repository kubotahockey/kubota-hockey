# Kubota Hockey — what changed

Everything below is in place and tested. All 20 routes plus the 4 POST/JSON
endpoints return successfully, and no page throws a JavaScript error.

---

## 1. Before you run it: the database

`app.py` reads `database/Kubota_Website_PROD.db`. The zip you sent contained an
**empty (0 byte) `hockey_reference.db`** and no PROD file, so the app could not
have started from it. I recovered the real 27 MB database from your git history
(commit `969297e`) to develop and test against.

Drop your `Kubota_Website_PROD.db` into `database/` and it will run. Database
resolution is now more forgiving:

1. `KUBOTA_DB_PATH` environment variable, if set
2. `database/Kubota_Website_PROD.db`
3. the largest non-empty `.db` in `database/`
4. otherwise a clear error naming the folder it searched — instead of the old
   opaque "no such table" failure much later in the boot

`app.secret_key` now reads `KUBOTA_SECRET_KEY` from the environment, falling
back to a dev value. **Set this in production.**

---

## 2. Bugs fixed

### `/teams` returned HTTP 500 on every request
`team_players` was sliced out of `dfm` *before* the loop that creates the
`PT_Y1..PT_Y7` columns, so the lookup raised
`KeyError: "None of [Index(['PT_Y1'...])] are in the [columns]"`. The loop now
runs before the slice.

### The team page charted meaningless data
- `top_team_projections` and `lowest_team_projections` were dicts of
  `{team: scalar}` for three teams, plotted against a seven-year axis. They are
  now genuine seven-year series for the single best and single worst team, and
  the legend names them.
- The seven positional rank bars were **hardcoded to `0`**, so every bar
  rendered at full length on every team. They are now computed for real
  (all forwards, all defence, top 12 forwards, top 6 defence, U23 forwards,
  U23 defence), each ranked league-wide by points per game.

### `/api/player_comps` produced invalid JSON
It emitted raw `NaN` (which is not valid JSON, so the browser's parse failed)
and requested columns that do not exist in `1YR_FINAL_COMPS` — `season`, `age`,
`fw_def`, `Height`, `Weight`, `draft_year`, `pick_number`. The comparables page
was blank as a result.

Rebuilt against the real schema (`season_2`, `height_cm`, `weight_lbs`,
`Draft Year`, `Overall`, `position`), NaN-safe, with working server-side
sorting on the clicked column. Age is **derived** from `date_of_birth` versus
`season_2`, since the table stores no age column — that is why `comp.age` used
to render as `undefined`.

### Player-page percentiles never worked
`scripts.js` writes to `#playerPercentiles` and binds `#exportButton`, but
neither element existed in `player.html`. The null `addEventListener` threw,
killing the rest of the handler. Both elements added; the JS is now null-guarded
throughout. Nothing ever supplied `GPPercentile`/`GPercentile`/`APercentile`/
`PTSPercentile` either — these are now computed server-side as a percentile rank
**within the player's own position group**.

### `/currentyear` loaded as an empty table
`data` was passed to the template and never used; rows only appeared after
clicking Calculate. The fantasy calculation is extracted into
`build_fantasy_table(form)`, shared by the AJAX endpoint and the initial render,
so the page arrives populated under standard 12-team points settings.

### Images 404'd on Linux
Templates asked for `currentyear.png`; the files are `currentyear.PNG`. Fine on
Windows, broken on any case-sensitive filesystem.

### CSS
- `styles.css` contained two literal `<style>` tags **inside the stylesheet**,
  which is a parse error that silently discarded the rules following each one.
- The footer was `#00e676` text on a `#00e676` background — invisible.
- A global rule underlined every `h1`–`h6` on the site.

### Smaller fixes
- Sticky table headers never engaged, because Bootstrap sets
  `border-collapse: collapse`, which disables `position: sticky` on `th`. Now
  `border-collapse: separate` with rules drawn on the cells. Tables with two
  header rows offset the second so it does not cover the first.
- Long team names wrapped onto two lines and doubled row heights.
- Undrafted players showed as draft year `0` and pick `300` (the dataset's
  sentinels). Now "Undrafted" / "—".
- The player chart's y-axis was hard-capped at 2.0 points per game, clipping the
  top of elite curves. Now `suggestedMax`, so it adapts.
- Bar widths could become `NaN%` when a maximum was zero or missing.
- The player card linked to `forecasts.html?player=…`, which is not a route.
- Duplicate/incorrect `data-sort` attributes on the PPP and SHP headers (both
  pointed at PPA/SHA).
- The forecasts grouped header declared `colspan` totalling 11 over 10 columns.
- The player chart had two titles — one in the panel, one drawn by Chart.js.
- DataTables was force-centring every column and ignoring the theme on its
  pagination; the forecasts page showed two search boxes.
- Select2 was loaded on every page and never initialised anywhere — removed.
- `base.html` had no `extra_scripts` block, so `forecasts.html` declared one that
  was silently discarded, and **every page loaded every page's JavaScript**.
  Scripts are now scoped to the pages that use them.

---

## 3. Redesign

Your existing structure, class names and JS hooks are all preserved — the
stylesheet is a drop-in replacement, not a rewrite of your markup contracts.

**Colour.** Taken from a rink at ice level rather than the previous
black-and-neon: boards navy `#071a2b`, panel `#0d2739`, crease blue `#4fa3d1`,
ice white `#eaf2f8`. Your green `#00e676` is kept as brand equity but restricted
to one job — the projection line and the primary action — so it reads as
meaningful rather than decorative. Red is reserved for negative values only.

**Type.** Barlow Condensed for headings and stat numerals (the vernacular of
scoreboards and sweater numbers), Inter for body and data tables with
`tabular-nums` so columns align.

**Structure.** A blue-line rule opens each section, echoing a zone change.
Navigation regrouped from six flat links into five dropdowns with active states,
which also surfaces `/teams` and `/player_comps` — both previously reachable
only by typing the URL.

**Homepage.** The hero is now a live projection curve of a real young forward
plotted against his three closest historical comparables, drawn from the
database at request time. That is what the product actually does, so it leads.

Also: visible keyboard focus rings, `prefers-reduced-motion` respected, and the
per-card hover-lift on everything removed so motion only answers actions.

---

## 4. New pages

All four are built from data already in your database.

| Route | What it does | Data it uses |
|---|---|---|
| `/leaders` | Top-ten boards per category, filterable by team, position, and total vs per-game | `FINAL_PROJECTIONS` |
| `/compare` | Up to four skaters on one axis; history dashed, projection solid | `1YR_FINAL_ROSTER_CLEAN` |
| `/value` | Cap hit against projected seven-year points, indexed to the league median, with full filtering and sorting | **`Cap Hit` + `CTRCT`, previously unused** |
| `/trade` | Fantasy trade analyzer — see below | `FINAL_PROJECTIONS` |

`DRAFT_PROJECTIONS_COMPS` was declared as `TABLE_COMPS_DRAFT` and never queried.
`Cap Hit` and `CTRCT` sat in the roster table unread. Both now have a home.

### Fantasy trade analyzer (`/trade`)

Prices a trade against **your** league, not a generic one. It runs the same
scoring engine as the projections table, which was refactored into
`compute_fantasy_frame(form)` so the two can never drift apart.

**Points leagues.** Each side is totalled in VORP — fantasy points above the
worst startable player at that position in a league your size. VORP is the right
currency for a trade because it already handles the 2-for-1 problem: a
replacement-level player is worth roughly zero, so packaging two mediocre
players rarely beats one good one. The page says this out loud when the sides
are uneven.

**Category leagues.** Switch the format and it scores the deal category by
category with full-season totals for each side, then reports the split (5-3, and
so on). Category chips turn individual cats on and off. Faceoff losses are
handled as lower-is-better.

**Settings.** The page carries the full set from `/currentyear`: league type,
position grouping (LW/C/RW/D or FW/DEF), season basis, team count, every roster
slot including utility and bench, all sixteen scoring fields, the defenceman
bonus, and all sixteen category checkboxes. Roster and scoring sit in collapsible
blocks so the page opens without a wall of inputs. Switching position grouping
swaps the roster row and disables the hidden one, so the server never receives a
conflicting pair.

These are not cosmetic. McDavid beats Brady Tkachuk by 147 points of value in a
standard league and loses to him by 455 in a hits-and-blocks league. Typing in a
scoring box re-prices the deal after a short pause.

The points-league verdict is judged on the gap as a share of the deal, not a
flat number, so sixty points between two stars reads as noise while sixty points
between two depth players reads as a fleecing. Everything is encoded in the URL.

### Contract value filters and sorting

The page now filters on position, team, contract expiry ("expires by 27/28"),
age range, cap-hit range in millions, and a minimum projected-points floor. Eight
sort keys are available (cost per point, value index, cap hit, projected points,
projected games, age, expiry, name) in either direction, from the dropdown or by
clicking a column header. Result size is selectable up to the full list.

Every control round-trips through the query string, so a filtered view is
linkable and the column-header sort links carry the active filters with them.

One detail worth knowing: the median used for the value index is computed across
every priced contract *before* filtering. Recomputing it per slice would make an
index of 100 mean something different on each view.

Proper 404 and 500 handlers were added — previously a bad URL returned raw
Werkzeug HTML.

---

## 5. Everything current-season runs on 84 games

The games-played choice is gone. `compute_fantasy_frame` now sets `GP` to 84 for
every skater, full stop, and the selector has been removed from both the
projections page and the trade analyzer. The injury-adjusted `GPNEW` basis is no
longer reachable, including by passing `season_length=GPNEW` in the URL.

The leaders board was still totalling on `GPNEW`, so it disagreed with the
projections table for the same player. It now uses 84 as well. The visible effect
is real: McDavid moves from 95 projected points to 114 and takes over first,
while MacKinnon drops from first to third because he had been carried by a higher
games projection.

Anything that legitimately depends on availability is untouched — the seven-year
pages and the contract-value page still use projected games (`GP2`), since a
seven-year total that assumed perfect health for everyone would be meaningless.

## 6. Removed pages

**Comparables tab.** `/player_comps`, `/api/player_comps` and
`templates/player_comps.html` are gone, along with the `COMPS_TABLE_VIEW` frame
built at boot solely to feed that endpoint.

**Draft class.** `/draft`, `templates/draft.html`, the `df_draft` loader and the
`TABLE_COMPS_DRAFT` constant are gone. That table is no longer read at startup,
so boot is a little quicker.

The comparables themselves are untouched — the top-ten table and the three
ghosted comparison curves on the player dashboard are core to the model and
still there. The derived `age` column on `df_comps` was kept for that reason.

`/player_comps` now returns the styled 404. If you would rather old links land
somewhere useful, a one-line redirect to `/player` would do it; say the word.

## 7. Bug fix: player pages failing to load

About 28% of player pages were showing "Failed to load player data."

`/get_player_data` returns the projection row, which includes the `cap_hit`
column added for the contract page. 514 of 1,820 skaters have no listed cap hit,
so that field came back as `NaN`. Python writes `NaN` as a bare token, which is
valid Python but **not** valid JSON, so the browser's `JSON.parse` threw and the
whole response was discarded. The server was returning 200 the entire time,
which is why it did not show up in route testing.

Fixed at the serialiser rather than at the one endpoint: `SafeJSONProvider`
converts every non-finite float to `null` before anything is written, so no
current or future endpoint can lose a response this way. Verified by
strict-parsing all 1,818 player payloads the way a browser does — zero failures,
where three of a twenty-player sample failed before.

Also hardened `/api/trade`, which read stats with `float(x or 0.0)`. `NaN` is
truthy in Python, so that idiom passes `NaN` straight through rather than
catching it.

While in there: the percentile donuts still used an old purple from the previous
palette, and pick number 300 (this dataset's undrafted sentinel) was showing as a
literal 300 in the comparables table.

**Errors now say what went wrong.** The old handler showed a blocking
`alert('Failed to load player data.')` for every possible failure — bad JSON, a
404, a 500, a dead server — which gave nobody anything to act on. The endpoint is
now wrapped so it always returns JSON (Flask's default 500 is an HTML page the
browser cannot parse, which produced that same useless message), and the page
renders the actual reason inline instead of behind an OK button. The full
response is logged to the console. There are no `alert()` calls left in the
player page.

**Belt and braces on the NaN fix.** The provider hook above only exists in
Flask 2.2+. `requirements.txt` pins 3.0.3, but `setup.py` allows `Flask>=1.1.2`,
so an older install would have silently ignored it and kept emitting `NaN`. The
player payload is now cleaned at the DataFrame level too (`_records()`), which
works on any Flask version. Verified by disabling the provider entirely and
re-running all 1,818 players: zero failures either way.

**`/healthz`** reports the build string, Flask and pandas versions, which
database file loaded, how many skaters are in it, whether JSON output is
NaN-safe, and a live parse check on a player with no cap hit. Open it in a
browser to see exactly what is running.

**The season selector is gone entirely.** Not disabled, not hidden — removed from
both settings panels, along with the now-dead `season_length` handling in
`app.py`. The engine hardcodes 84 games.

## 8. Files

Changed: `app.py`, `static/css/styles.css`, `static/js/scripts.js`,
`static/js/forecasts_scripts.js`, and every template.

New: `templates/leaders.html`, `compare.html`, `value.html`, `draft.html`,
`trade.html`, `error.html`.

Deleted: `templates/player_comps.html`, `templates/draft.html`.

`static/css/styles.original.css` is your original stylesheet, kept so you can
diff. Delete it whenever you like.

Untouched: `login.html`, `register.html`, `upgrade.html` (no routes exist for
these — they reference `url_for('login')` and would raise if ever rendered),
`team_insights.html` and `team_insights.js` (both empty files).
