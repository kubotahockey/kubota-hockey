#!/usr/bin/env python3
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.datastructures import MultiDict
from flask.json.provider import DefaultJSONProvider
import pandas as pd
import numpy as np
from sqlalchemy import create_engine
import io, csv, random
import math
from pathlib import Path
import os

KUBOTA_BUILD = "2026-09-05 nan-safe"

app = Flask(__name__)
app.secret_key = os.getenv("KUBOTA_SECRET_KEY", "dev-only-change-me")


# -----------------------------------------------------------------------------
# JSON safety
# -----------------------------------------------------------------------------
# Python writes float('nan') as a bare NaN token, which is valid Python but NOT
# valid JSON -- the browser's JSON.parse throws on it and the whole response is
# lost. Any missing number coming out of pandas (a player with no listed cap
# hit, a rate with no games behind it) would take a page down with it, so every
# non-finite value becomes null before it is serialised.
def _json_safe(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


class SafeJSONProvider(DefaultJSONProvider):
    def dumps(self, obj, **kwargs):
        return super().dumps(_json_safe(obj), **kwargs)


app.json = SafeJSONProvider(app)


def _records(frame):
    """DataFrame -> list of dicts with every missing value as None.

    Done here rather than relying only on the JSON provider above, so the
    payload is valid JSON regardless of which Flask version is installed.
    setup.py allows Flask>=1.1.2, and the provider hook only exists in 2.2+.
    """
    clean = frame.replace([np.inf, -np.inf], np.nan)
    return clean.astype(object).where(pd.notna(clean), None).to_dict(orient='records')

# =============================================================================
# DB CONFIG (cross-platform: works on Windows & Linux)
# =============================================================================

# Resolve DB path relative to this file so it works on both Windows and Linux
BASE_DIR = Path(__file__).resolve().parent
DB_DIR = BASE_DIR / "database"


def _resolve_db_path() -> str:
    """Find the projections DB.

    Order: KUBOTA_DB_PATH env var -> the expected PROD file -> any non-empty
    .db in database/. Raises with a readable message instead of failing later
    with an opaque 'no such table' error.
    """
    override = os.getenv("KUBOTA_DB_PATH")
    if override:
        return str(Path(override).resolve())

    preferred = DB_DIR / "Kubota_Website_PROD.db"
    if preferred.exists() and preferred.stat().st_size > 0:
        return str(preferred.resolve())

    candidates = sorted(
        (p for p in DB_DIR.glob("*.db") if p.stat().st_size > 0),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if candidates:
        return str(candidates[0].resolve())

    raise RuntimeError(
        f"No usable SQLite database found in {DB_DIR}. Expected "
        f"Kubota_Website_PROD.db, or set the KUBOTA_DB_PATH environment variable."
    )


DB_PROD_PATH = _resolve_db_path()

engine = create_engine(f"sqlite:///{DB_PROD_PATH}")

# Table names used below
TABLE_FINAL        = "FINAL_PROJECTIONS"
TABLE_ROSTER_CLEAN = "1YR_FINAL_ROSTER_CLEAN"
TABLE_COMPS_1YR    = "1YR_FINAL_COMPS"

# Optional: quick sanity check so errors are clearer
def _assert_table(conn_engine, table_name):
    from sqlalchemy.exc import SQLAlchemyError
    try:
        with conn_engine.connect() as conn:
            conn.exec_driver_sql(f'SELECT 1 FROM [{table_name}] LIMIT 1')
    except SQLAlchemyError as e:
        raise RuntimeError(
            f"SQLite table [{table_name}] not found in DB: {DB_PROD_PATH}"
        ) from e
        
        
LAST_UPDATE = "September 4, 2026"

# =============================================================================
# HELPERS
# =============================================================================
def pick(df: pd.DataFrame, *cands):
    """Return the first column in df that matches any candidate (case-insensitive)."""
    cl = {c.lower(): c for c in df.columns}
    for cand in cands:
        if cand and cand.lower() in cl:
            return cl[cand.lower()]
    return None

# =============================================================================
# LOAD FROM DB
# =============================================================================
final_raw  = pd.read_sql(f"SELECT * FROM [{TABLE_FINAL}];", con=engine)
roster_raw = pd.read_sql(f"SELECT * FROM [{TABLE_ROSTER_CLEAN}];", con=engine)

# -----------------------------------------------------------------------------
# A) CURRENT YEAR: df_final_projections (FINAL_PROJECTIONS ONLY)
# -----------------------------------------------------------------------------
stats = final_raw.copy()

# Rename to UI-friendly names your templates expect
rename_map_stats = {
    "Player": "name",
    "player_link_ep": "Link",
    "Position": "Pos",
    "Team": "team",
    "PPG_GP": "PPG",
    "PPA_GP": "PPA",
    "SHG_GP": "SHG",
    "SHA_GP": "SHA",
}
stats.rename(columns={k: v for k, v in rename_map_stats.items() if k in stats.columns}, inplace=True)

# GPNEW = 84 * GP_Percent (fallback 84)
if "GPNEW" not in stats.columns:
    if "GP_Percent" in stats.columns:
        stats["GPNEW"] = (84 * pd.to_numeric(stats["GP_Percent"], errors="coerce")).clip(0, 84)
    else:
        stats["GPNEW"] = 84.0
stats["GPNEW"] = pd.to_numeric(stats["GPNEW"], errors="coerce").fillna(0.0)

# Attach Image via roster (logo) by team (do NOT mix stats, only logos)
roster_for_logo = roster_raw.copy()
if "Team" not in roster_for_logo.columns and "team" in roster_for_logo.columns:
    roster_for_logo.rename(columns={"team": "Team"}, inplace=True)
logo_map = roster_for_logo[["Team", "logo"]].drop_duplicates().rename(columns={"logo": "Image"})

left_team = "team" if "team" in stats.columns else ("Team" if "Team" in stats.columns else None)
if left_team is not None:
    stats = stats.merge(logo_map, left_on=left_team, right_on="Team", how="left")
    if "Team" in stats.columns and left_team != "Team":
        stats.drop(columns=["Team"], inplace=True)

# Normalize positions to legacy expectations
if "Pos" in stats.columns:
    stats["Pos"] = stats["Pos"].replace({"W": "RW", "F": "C"})

# Thin to exact columns used by /currentyear
CURRENT_COLS = [
    'Link','name','team','Image','Pos','Age','GPNEW',
    'G_GP','A_GP','PTS_GP','SOG_GP','PIM_GP','PLUSMINUS_GP',
    'PPG','PPA','SHG','SHA','BLK_GP','HIT_GP','FOL_GP','FOW_GP'
]
for c in CURRENT_COLS:
    if c not in stats.columns:
        stats[c] = np.nan
df_final_projections = stats[CURRENT_COLS].copy()

# -----------------------------------------------------------------------------
# B) FORECASTS/TEAMS: df_projections & df_merged (ROSTER ONLY)
# -----------------------------------------------------------------------------
R = roster_raw.copy()

# Map roster columns you listed → stable names
colmap = {
    "name": "name",
    "position": "Pos",
    "age": "Age",
    "team": "team",
    "player_link": "link",
    "logo": "Image",
    "overall":"overall",
    "draft_year":"draft_year",
    "height":"Height",
    "weight":"weight",

    # 3-year “current” slice (for totals)
    "gp_3": "gp_3",
    "gpg_3": "gpg_3",
    "apg_3": "apg_3",
    "pts_pg_3": "pts_pg_3",
    "pimpg_3": "pimpg_3",
}
for src, dst in colmap.items():
    if src in R.columns and src != dst:
        R.rename(columns={src: dst}, inplace=True)

# Ensure required columns
if "Pos" not in R.columns and "position" in roster_raw.columns:
    R["Pos"] = roster_raw["position"]
if "Image" not in R.columns:
    R["Image"] = "default_logo.png"
if "link" not in R.columns:
    R["link"] = ""

# Coerce numeric
for c in ["gp_3", "gpg_3", "apg_3", "pts_pg_3", "pimpg_3"]:
    if c in R.columns:
        R[c] = pd.to_numeric(R[c], errors="coerce")

# GP2 for totals = gp_3 (fallback 84)
R["GP2"] = R.get("gp_3", 84).fillna(84).clip(lower=0, upper=84)

# Normalize positions to legacy expectations
R["Pos"] = R.get("Pos", "").replace({"W": "RW", "F": "C"})

# Build forecasts/teams-compatible DataFrame
df_projections = pd.DataFrame({
    "name":   R.get("name", ""),
    "fw_def": np.where(R["Pos"].eq("D"), "DEF", "FW"),
    "height": R.get("height", ""),
    "weight": R.get("weight", ""),
    "overall": R.get("overall", ""),
    "draft_year": R.get("draft_year", ""),
    "age":    R.get("Age", np.nan),
    "GP2":    R["gp_total"],
    "GTOT":   R.get("g_total"),
    "ATOT":   R.get("a_total"),
    "PTSTOT": R.get("pts_total"),
    "PIM2":   R.get("pimpg_3", 0.0).fillna(0.0)  * R["GP2"],
    "G_per":  R["g_total"]/R["gp_total"],
    "A_per":  R["a_total"]/R["gp_total"],
    "PTS_Per":R["pts_total"]/R["gp_total"],
    "link":   R.get("link", ""),
    "team":   R.get("team", ""),
    "Image":  R.get("Image", "default_logo.png"),
    "pts_pg_1": R["pts_pg_1"],
    "pts_pg_2": R["pts_pg_2"]
})
df_projections["PIM"] = df_projections["PIM2"]

# Contract data lives in the roster table but was never surfaced anywhere.
_cap_raw = R.get("Cap Hit", pd.Series(index=R.index, dtype="object"))
df_projections["cap_hit"] = pd.to_numeric(
    _cap_raw.astype(str).str.replace(r"[^0-9.]", "", regex=True).replace("", np.nan),
    errors="coerce",
)
df_projections["contract"] = R.get("CTRCT", pd.Series(index=R.index, dtype="object")).astype(str)

# ---------- map 7 seasons from roster per-season columns ----------
# ensure numeric for the gp_* and pts_pg_* columns we’ll use
for k in range(3, 10):
    for col in (f'gp_{k}', f'pts_pg_{k}'):
        if col in R.columns:
            R[col] = pd.to_numeric(R[col], errors='coerce')

# TOTPT_Y1..7 = pts_pg_3..9  (per-game)
# GPY1..7     = gp_3..9      (games played)
for y, x in enumerate(range(3, 10), start=1):
    df_projections[f'TOTPT_Y{y}'] = R.get(f'pts_pg_{x}', 0).fillna(0.0)
    df_projections[f'GPY{y}']     = R.get(f'gp_{x}', 0).fillna(0.0)


# df_logos + df_merged (compat with original)
df_logos = df_projections[["link", "team", "Image"]].drop_duplicates().rename(columns={"link": "URL", "team": "Team"})
df_merged = df_projections.merge(df_logos[['URL', 'Team', 'Image']], left_on='link', right_on='URL', how='left')

# Normalize Team/Image in df_merged for safety
if "Team" not in df_merged.columns and "team" in df_merged.columns:
    df_merged.rename(columns={"team": "Team"}, inplace=True)
img_cols = [c for c in df_merged.columns if c.lower().startswith("image")]
if "Image" not in df_merged.columns:
    df_merged["Image"] = df_merged[img_cols].bfill(axis=1).iloc[:, 0] if img_cols else "default_logo.png"
for c in img_cols:
    if c != "Image":
        df_merged.drop(columns=c, inplace=True, errors="ignore")

# -----------------------------------------------------------------------------
# C) COMPS: unify with your exact names (anchor/Comparables/SCORE)
# -----------------------------------------------------------------------------
# -----------------------------
# COMPS: load EVERYTHING + add aliases + 7-year fields
# -----------------------------
df_comps = pd.read_sql(f"SELECT * FROM [{TABLE_COMPS_1YR}];", con=engine)

# Keep original names (target_player, player, similarity) AND add the aliases your app expects
if 'target_player' in df_comps.columns:
    df_comps['anchor'] = df_comps['target_player']
if 'player' in df_comps.columns:
    df_comps['Comparables'] = df_comps['player']
if 'similarity' in df_comps.columns:
    df_comps['SCORE'] = pd.to_numeric(df_comps['similarity'], errors='coerce')

# Ensure numeric types for seasonal columns we’ll use
for k in range(3, 10):
    for base in ['gp', 'gpg', 'apg', 'pts_pg', 'pimpg']:
        col = f'{base}_{k}'
        if col in df_comps.columns:
            df_comps[col] = pd.to_numeric(df_comps[col], errors='coerce')

# Map 7 seasons:
# TOTPT_Y1..Y7 = pts_pg_3..pts_pg_9 (per-game points)
# GPY1..Y7     = gp_3..gp_9         (games played)
for y, x in enumerate(range(3, 10), start=1):
    df_comps[f'TOTPT_Y{y}'] = df_comps.get(f'ptspg_{x}', 0)
    df_comps[f'GPY{y}']     = df_comps.get(f'gp_{x}', 0)

# Age at the comparable season. The comps table stores a date of birth and the
# season the comparable is anchored to, but never an age -- so anything asking
# for comp.age used to render "undefined".
_dob = pd.to_datetime(df_comps.get('date_of_birth'), errors='coerce')
_season = pd.to_numeric(df_comps.get('season_2'), errors='coerce')
df_comps['age'] = (_season - _dob.dt.year).round(0)
df_comps.loc[(df_comps['age'] < 15) | (df_comps['age'] > 50), 'age'] = np.nan

# =============================================================================
# ROUTES
# =============================================================================
def _featured_curve():
    """Pick a recognisable young forward and return his curve plus his three
    closest historical comparables. This is what the homepage leads with."""
    pool = df_projections.copy()
    pool['age'] = pd.to_numeric(pool['age'], errors='coerce')
    pool['PTSTOT'] = pd.to_numeric(pool['PTSTOT'], errors='coerce')
    young = pool[(pool['age'] >= 19) & (pool['age'] <= 25)].sort_values('PTSTOT', ascending=False)
    row = (young if not young.empty else pool.sort_values('PTSTOT', ascending=False)).head(1)
    if row.empty:
        return None
    r = row.iloc[0]

    def series(src, prefix):
        out = []
        for y in range(1, 8):
            v = pd.to_numeric(src.get(f'{prefix}{y}'), errors='coerce')
            out.append(None if pd.isna(v) else round(float(v), 3))
        return out

    comps = df_comps[df_comps['anchor'] == r.get('link')].sort_values('SCORE', ascending=False).head(3)
    return {
        'name': r['name'],
        'team': r.get('team', ''),
        'age': None if pd.isna(r['age']) else round(float(r['age']), 1),
        'curve': series(r, 'TOTPT_Y'),
        'comps': [{'name': c['Comparables'],
                   'score': round(float(c['SCORE']), 2) if pd.notna(c['SCORE']) else None,
                   'curve': series(c, 'TOTPT_Y')}
                  for _, c in comps.iterrows()],
    }


@app.route('/')
def home():
    return render_template(
        'index.html',
        meta_title="Kubota Hockey - NHL Projections",
        meta_description="Premium Statistical Projection System",
        featured=_featured_curve(),
        n_players=int(df_projections['name'].nunique()),
        n_comps=int(len(df_comps)),
        n_teams=int(df_projections['team'].nunique()),
    )

@app.context_processor
def inject_last_update():
    return dict(last_update=LAST_UPDATE)

@app.route('/forecasts')
def forecasts():
    selected_columns = [
        'name', 'fw_def', 'age', 'GP2', 'GTOT', 'ATOT', 'PTSTOT', 'PIM2', 'G_per', 'A_per', 'PTS_Per'
    ]
    df_selected = df_projections[selected_columns].copy()
    df_selected = df_selected[~np.isinf(df_selected['PTSTOT'])]
    df_selected = df_selected.round(2).sort_values(by='PTSTOT', ascending=False)
    columns = df_selected.columns.tolist()
    data = df_selected.to_dict(orient='records')
    return render_template('forecasts.html', columns=columns, data=data)

@app.route('/currentyear')
def currentyear():
    cols = [
        'Link','name','team','Image','Pos','Age','GPNEW',
        'G_GP','A_GP','PTS_GP','SOG_GP','PIM_GP','PLUSMINUS_GP',
        'PPG','PPA','SHG','SHA','BLK_GP','HIT_GP','FOL_GP','FOW_GP'
    ]
    df_selected = df_final_projections[cols].copy().round(2)
    data = df_selected.to_dict(orient='records')
    # Pre-render the table with default league settings so the page has content
    # before the user touches the form.
    initial_rows = build_fantasy_table(DEFAULT_SCORING)
    if not isinstance(initial_rows, str):
        initial_rows = ''
    return render_template('currentyear.html', data=data, initial_rows=initial_rows)


DEFAULT_SCORING = MultiDict([
    ('league_type', 'points'), ('position_grouping', 'split'),
    ('teams', '12'),
    ('lw_starters', '2'), ('rw_starters', '2'), ('c_starters', '2'),
    ('d_starters', '4'), ('util_starters', '1'), ('bench_split', '4'),
    ('g_points', '6'), ('a_points', '4'), ('pts_points', '0'),
    ('sog_points', '0.9'), ('pim_points', '0'), ('plusminus_points', '0'),
    ('ppg_points', '2'), ('ppa_points', '2'), ('ppp_points', '0'),
    ('shg_points', '0'), ('sha_points', '0'), ('shp_points', '0'),
    ('blk_points', '0.5'), ('hit_points', '0'), ('fol_points', '0'),
    ('fow_points', '0'), ('defensive_points', '0'),
])


@app.route('/calculate_fantasy_points', methods=['POST'])
def calculate_fantasy_points():
    return build_fantasy_table(request.form)


def compute_fantasy_frame(form):
    """Score every skater under `form`'s league settings.

    Returns the full projections frame with FantasyPoints, PosGroup and VORP
    added, sorted by VORP. Shared by the projections table and the trade
    analyzer so both price players the same way.
    """
    if True:
        # --- Inputs ---
        league_type = (form.get('league_type') or 'points').strip().lower()
        position_grouping = (form.get('position_grouping') or 'split').strip().lower()  # 'split' or 'fw_def'
        teams = int(form.get('teams', 12))
        util_starters = int(form.get('util_starters', 0))
        util_total = teams * max(util_starters, 0)

        # Roster slots (starters only)
        if position_grouping == 'split':
            slots_LW = int(form.get('lw_starters', 2))
            slots_RW = int(form.get('rw_starters', 2))
            slots_C  = int(form.get('c_starters', 2))
            slots_D  = int(form.get('d_starters', 4))
            roster_counts = {
                'LW': teams * max(slots_LW, 0),
                'RW': teams * max(slots_RW, 0),
                'C' : teams * max(slots_C,  0),
                'D' : teams * max(slots_D,  0),
            }
            bench_total = teams * max(int(form.get('bench_split', 0)), 0)
        else:  # 'fw_def'
            slots_F  = int(form.get('fw_starters', 6))
            slots_D  = int(form.get('def_starters', 4))
            roster_counts = {
                'F': teams * max(slots_F, 0),
                'D': teams * max(slots_D, 0),
            }
            bench_total = teams * max(int(form.get('bench_fwdef', 0)), 0)

        # DAILY-LINEUP streaming factor (0..1). 0.6 ≈ typical nightly streaming.
        bench_weight = float(form.get('bench_weight', 0.6))
        stream_total = int(math.floor(bench_total * max(min(bench_weight, 1.0), 0.0)))

        # Scoring weights (Points league). PTS added.
        scoring_settings = {
            'G': float(form.get('g_points', 6)),
            'A': float(form.get('a_points', 4)),
            'PTS': float(form.get('pts_points', 0)),  # NEW
            'SOG': float(form.get('sog_points', 0.9)),
            'PIM': float(form.get('pim_points', 0)),
            'PLUSMINUS': float(form.get('plusminus_points', 2)),
            'PPG': float(form.get('ppg_points', 2)),
            'PPA': float(form.get('ppa_points', 2)),
            'PPP': float(form.get('ppp_points', 0)),  # keep 0 in points leagues to avoid double counting PP
            'SHG': float(form.get('shg_points', 0)),
            'SHA': float(form.get('sha_points', 0)),
            'SHP': float(form.get('shp_points', 0)),
            'BLK': float(form.get('blk_points', 0.5)),
            'HIT': float(form.get('hit_points', 0)),
            'FOL': float(form.get('fol_points', 0)),
            'FOW': float(form.get('fow_points', 0)),
        }
        defensive_points_multiplier = float(form.get('defensive_points', 0))

        # --- Data ---
        df_selected = df_final_projections.copy()

        # Everyone is projected over a full 84-game season, so players are
        # compared on production rather than on availability.
        df_selected['GP'] = 84.0

        # Convenience totals
        df_selected['PPP'] = df_selected['PPG'] + df_selected['PPA']
        df_selected['SHP'] = df_selected['SHG'] + df_selected['SHA']
        df_selected['PTS_GP'] = df_selected['G_GP'] + df_selected['A_GP']  # NEW

        # Ensure numeric inputs
        num_cols = [
            'GP','G_GP','A_GP','SOG_GP','PIM_GP','PLUSMINUS_GP',
            'PPG','PPA','PPP','SHG','SHA','SHP','BLK_GP','HIT_GP','FOL_GP','FOW_GP','PTS_GP'
        ]
        for c in num_cols:
            if c in df_selected.columns:
                df_selected[c] = pd.to_numeric(df_selected[c], errors='coerce').fillna(0.0)
        df_selected['Pos'] = df_selected['Pos'].astype(str)

        # --- Fantasy Points ---
        if league_type == 'points':
            # Include PTS weight. To avoid double counting, set G=A=0 if you use PTS>0.
            df_selected['FantasyPoints'] = (
                df_selected['G_GP'] * df_selected['GP'] * scoring_settings['G'] +
                df_selected['A_GP'] * df_selected['GP'] * scoring_settings['A'] +
                df_selected['PTS_GP'] * df_selected['GP'] * scoring_settings['PTS'] +  # NEW
                df_selected['SOG_GP'] * df_selected['GP'] * scoring_settings['SOG'] +
                df_selected['PIM_GP'] * df_selected['GP'] * scoring_settings['PIM'] +
                df_selected['PLUSMINUS_GP'] * df_selected['GP'] * scoring_settings['PLUSMINUS'] +
                df_selected['PPG'] * df_selected['GP'] * scoring_settings['PPG'] +
                df_selected['PPA'] * df_selected['GP'] * scoring_settings['PPA'] +
                df_selected['PPP'] * df_selected['GP'] * scoring_settings['PPP'] +
                df_selected['SHG'] * df_selected['GP'] * scoring_settings['SHG'] +
                df_selected['SHA'] * df_selected['GP'] * scoring_settings['SHA'] +
                df_selected['SHP'] * df_selected['GP'] * scoring_settings['SHP'] +
                df_selected['BLK_GP'] * df_selected['GP'] * scoring_settings['BLK'] +
                df_selected['HIT_GP'] * df_selected['GP'] * scoring_settings['HIT'] +
                df_selected['FOL_GP'] * df_selected['GP'] * scoring_settings['FOL'] +
                df_selected['FOW_GP'] * df_selected['GP'] * scoring_settings['FOW']
            )
            # D-men bonus on (G + A)
            is_d = df_selected['Pos'].str.contains('D', na=False)
            df_selected.loc[is_d, 'FantasyPoints'] += (
                (df_selected.loc[is_d, 'G_GP'] * df_selected.loc[is_d, 'GP'] +
                 df_selected.loc[is_d, 'A_GP'] * df_selected.loc[is_d, 'GP']) * defensive_points_multiplier
            )

        else:
            # CATEGORIES: checkboxes named "categories" control inclusion (Z-score)
            # Values must match keys we derive below (G, A, PTS, SOG, PIM, PLUSMINUS, PPG, PPA, PPP, SHG, SHA, SHP, BLK, HIT, FOL, FOW)
            included_cats = set(form.getlist('categories'))

            cat_cols = [
                'G_GP','A_GP','PTS_GP',  # include PTS
                'SOG_GP','PIM_GP','PLUSMINUS_GP',
                'PPG','PPA','PPP','SHG','SHA','SHP','BLK_GP','HIT_GP','FOL_GP','FOW_GP'
            ]
            df_selected['FantasyPoints'] = 0.0
            for c in cat_cols:
                total_col = c + '_Total'
                df_selected[total_col] = df_selected[c] * df_selected['GP']
                m = df_selected[total_col].mean()
                s = df_selected[total_col].std()

                # Map column name to checkbox key
                key = c.replace('_GP', '')  # e.g., 'PTS_GP' -> 'PTS', 'BLK_GP' -> 'BLK', 'PPG' -> 'PPG'
                mult = 1.0 if key in included_cats else 0.0

                if mult != 0 and s and s != 0:
                    df_selected['FantasyPoints'] += ((df_selected[total_col] - m) / s) * mult

        # Normalize FP
        df_selected['FantasyPoints'] = pd.to_numeric(df_selected['FantasyPoints'], errors='coerce').fillna(0.0)

        # --- Position grouping for VORP ---
        def to_pos_group(pos: str) -> str:
            s = pos or ''
            if 'D' in s:
                return 'D'
            if position_grouping == 'split':
                if 'LW' in s: return 'LW'
                if 'C'  in s: return 'C'
                if 'RW' in s: return 'RW'
                return 'C'  # fallback forward bucket
            else:
                return 'F'

        df_selected['PosGroup'] = df_selected['Pos'].apply(to_pos_group)

        # --- Roster selection: POS -> UTIL -> STREAM ---
        df_selected['Rostered'] = False
        df_selected['RosterSource'] = ''

        # Step 1: position-locked starters
        for grp, k in roster_counts.items():
            k = max(int(k), 0)
            if k == 0:
                continue
            grp_pool = df_selected.loc[df_selected['PosGroup'] == grp, 'FantasyPoints']
            take = min(k, len(grp_pool))
            if take > 0:
                grp_idx = grp_pool.nlargest(take).index
                df_selected.loc[grp_idx, 'Rostered'] = True
                df_selected.loc[grp_idx, 'RosterSource'] = 'POS'

        # Step 2: utility (any skater)
        if util_total > 0:
            remaining = df_selected.loc[~df_selected['Rostered']]
            util_take = min(util_total, len(remaining))
            if util_take > 0:
                util_idx = remaining['FantasyPoints'].nlargest(util_take).index
                df_selected.loc[util_idx, 'Rostered'] = True
                df_selected.loc[util_idx, 'RosterSource'] = 'UTIL'

        # Step 3: stream (a fraction of bench acts like starters over the season)
        if stream_total > 0:
            remaining2 = df_selected.loc[~df_selected['Rostered']]
            stream_take = min(stream_total, len(remaining2))
            if stream_take > 0:
                stream_idx = remaining2['FantasyPoints'].nlargest(stream_take).index
                df_selected.loc[stream_idx, 'Rostered'] = True
                df_selected.loc[stream_idx, 'RosterSource'] = 'STREAM'

        # --- Replacement baselines from ACTUAL rostered set ---
        rostered_df = df_selected.loc[df_selected['Rostered']]
        baselines = {}
        for grp, sub in rostered_df.groupby('PosGroup'):
            baselines[grp] = float(sub['FantasyPoints'].min()) if not sub.empty else 0.0

        df_selected['AvgPosFP'] = df_selected['PosGroup'].map(lambda g: baselines.get(g, 0.0)).fillna(0.0)

        # --- VORP ---
        df_selected['VORP'] = df_selected['FantasyPoints'] - df_selected['AvgPosFP']

        # Sort by VORP
        df_selected = df_selected.sort_values(by='VORP', ascending=False)

        return df_selected


def build_fantasy_table(form):
    """Render the projections table body. Wraps the scoring engine so the
    /currentyear page and its AJAX endpoint share one code path."""
    try:
        df_selected = compute_fantasy_frame(form)
    except Exception as e:
        return f"An error occurred during the calculation: {str(e)}", 500

    rows = []
    rank = 0
    for _, row in df_selected.iterrows():
        rank += 1
        rows.append(
            '<tr>'
            f'<td class="rank-cell">{rank}</td>'
            f'<td class="t" data-key="name">{row["name"]}</td>'
            f'<td class="t" data-key="team">{row["team"]}</td>'
            f'<td class="t" data-key="Pos"><span class="badge-pos">{row["Pos"]}</span></td>'
            f'<td data-key="GP">{round(row["GP"], 2)}</td>'
            f'<td data-key="G_GP">{round(row["G_GP"] * row["GP"], 2)}</td>'
            f'<td data-key="A_GP">{round(row["A_GP"] * row["GP"], 2)}</td>'
            f'<td data-key="PTS_GP">{round((row["G_GP"] + row["A_GP"]) * row["GP"], 2)}</td>'
            f'<td data-key="SOG_GP">{round(row["SOG_GP"] * row["GP"], 2)}</td>'
            f'<td data-key="PIM_GP">{round(row["PIM_GP"] * row["GP"], 2)}</td>'
            f'<td data-key="PLUSMINUS_GP">{round(row["PLUSMINUS_GP"] * row["GP"], 2)}</td>'
            f'<td data-key="PPG">{round(row["PPG"] * row["GP"], 2)}</td>'
            f'<td data-key="PPA">{round(row["PPA"] * row["GP"], 2)}</td>'
            f'<td data-key="PPP">{round((row["PPG"] + row["PPA"]) * row["GP"], 2)}</td>'
            f'<td data-key="SHG">{round(row["SHG"] * row["GP"], 2)}</td>'
            f'<td data-key="SHA">{round(row["SHA"] * row["GP"], 2)}</td>'
            f'<td data-key="SHP">{round((row["SHG"] + row["SHA"]) * row["GP"], 2)}</td>'
            f'<td data-key="BLK_GP">{round(row["BLK_GP"] * row["GP"], 2)}</td>'
            f'<td data-key="HIT_GP">{round(row["HIT_GP"] * row["GP"], 2)}</td>'
            f'<td data-key="FOL_GP">{round(row["FOL_GP"] * row["GP"], 2)}</td>'
            f'<td data-key="FOW_GP">{round(row["FOW_GP"] * row["GP"], 2)}</td>'
            f'<td data-key="FantasyPoints">{round(row["FantasyPoints"], 2)}</td>'
            f'<td data-key="VORP">{round(row["VORP"], 2)}</td>'
            '</tr>'
        )
    return ''.join(rows)


@app.route('/export_csv', methods=['POST'])
def export_csv():
    try:
        table_data = request.json.get('tableData', [])
        csv_data = io.StringIO()
        writer = csv.writer(csv_data)
        for row in table_data:
            writer.writerow(row)
        csv_data.seek(0)
        return send_file(
            io.BytesIO(csv_data.getvalue().encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name='kubota_hockey_2024_2025.csv'
        )
    except Exception:
        return "An error occurred during the CSV export.", 500

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/player')
def player_page():
    # Use the roster-driven list
    players = df_projections['name'].dropna().unique().tolist()
    # Safe default if list is empty
    random_player = request.args.get('player') or (random.choice(players) if players else "")
    return render_template('player.html', players=players, random_player=random_player)

@app.route('/get_player_data', methods=['POST'])
def get_player_data():
    """Everything the player dashboard needs, as JSON.

    Wrapped so that an unexpected failure still returns JSON. Flask's default
    500 is an HTML page, which the browser cannot parse, so the page would show
    a generic "failed to load" with nothing useful behind it.
    """
    try:
        return _player_payload((request.form.get('player_name') or '').strip())
    except Exception as exc:
        app.logger.exception('get_player_data failed')
        return jsonify({'error': f'{type(exc).__name__}: {exc}'}), 500


def _player_payload(player_name):
    if not player_name:
        return jsonify({'error': 'No player name was sent.'}), 400

    # Use df_projections (roster-driven)
    rows = df_projections[df_projections['name'] == player_name]
    if rows.empty:
        return jsonify({'error': f'No projection on file for "{player_name}".'}), 404

    projection_data = _records(rows)

    # Anchor/link for comps + image comes from df_projections['link']
    anchor = rows['link'].iloc[0] if 'link' in rows.columns else ""

    # Comps joined on anchor (target_player in DB)
    comps_data = _records(df_comps[df_comps['anchor'] == anchor].fillna(0))

    # Image via df_logos (built from df_projections)
    try:
        image_link = df_logos.loc[df_logos['URL'] == anchor, 'Image'].iloc[0]
    except Exception:
        image_link = ''

    # Percentile rank within the same position group. The player page has always
    # charted these but nothing ever supplied them, so they rendered as NaN%.
    group = df_projections[df_projections['fw_def'] == rows['fw_def'].iloc[0]]
    for key, col in (('GPPercentile', 'GP2'), ('GPercentile', 'GTOT'),
                     ('APercentile', 'ATOT'), ('PTSPercentile', 'PTSTOT')):
        series = pd.to_numeric(group[col], errors='coerce')
        mine = pd.to_numeric(rows[col].iloc[0], errors='coerce')
        if pd.isna(mine) or series.notna().sum() == 0:
            projection_data[0][key] = 0.0
        else:
            projection_data[0][key] = round(float((series < mine).mean()), 4)

    return jsonify({'projection': projection_data, 'comps': comps_data, 'image_link': image_link})

# -----------------------------------------------------------------------------
# FANTASY TRADE ANALYZER
# -----------------------------------------------------------------------------
# key, label, column expression, higher-is-better.
# This mirrors the category checkboxes on /currentyear exactly, so a league set
# up on one page scores the same on the other.
FANTASY_CATS = [
    ('G',         'Goals',          'G_GP',         True),
    ('A',         'Assists',        'A_GP',         True),
    ('PTS',       'Points',         'PTS_GP',       True),
    ('SOG',       'Shots',          'SOG_GP',       True),
    ('PPG',       'PP goals',       'PPG',          True),
    ('PPA',       'PP assists',     'PPA',          True),
    ('PPP',       'PP points',      'PPP',          True),
    ('SHG',       'SH goals',       'SHG',          True),
    ('SHA',       'SH assists',     'SHA',          True),
    ('SHP',       'SH points',      'SHP',          True),
    ('BLK',       'Blocks',         'BLK_GP',       True),
    ('HIT',       'Hits',           'HIT_GP',       True),
    ('PIM',       'PIM',            'PIM_GP',       True),
    ('PLUSMINUS', 'Plus/minus',     'PLUSMINUS_GP', True),
    ('FOW',       'Faceoff wins',   'FOW_GP',       True),
    ('FOL',       'Faceoff losses', 'FOL_GP',       False),
]

DEFAULT_CATS = ['G', 'A', 'PTS', 'SOG', 'PPP', 'BLK', 'HIT', 'PLUSMINUS']


def _league_form(args):
    """Merge the query string over the default league settings, so the trade
    analyzer can be called with only the settings the manager changed."""
    form = MultiDict(DEFAULT_SCORING)
    for key in args.keys():
        if key in ('a', 'b'):
            continue
        values = args.getlist(key)
        form.setlist(key, values)
    if 'categories' not in args and (args.get('league_type') or '') == 'categories':
        form.setlist('categories', DEFAULT_CATS)
    return form


@app.route('/trade')
def trade():
    players = sorted(df_final_projections['name'].dropna().unique().tolist())
    return render_template('trade.html', players=players,
                           cats=FANTASY_CATS, default_cats=DEFAULT_CATS)


@app.route('/api/trade')
def api_trade():
    args = request.args
    league_type = (args.get('league_type') or 'points').strip().lower()
    form = _league_form(args)

    try:
        frame = compute_fantasy_frame(form)
    except Exception as exc:
        return jsonify({'error': f'Could not score that league setup: {exc}'}), 400

    frame = frame.set_index('name', drop=False)
    included = set(form.getlist('categories')) or set(DEFAULT_CATS)

    def pick(names):
        out = []
        for n in names:
            if n in frame.index:
                row = frame.loc[n]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                out.append(row)
        return out

    def side(rows):
        players, totals = [], {k: 0.0 for k, _, _, _ in FANTASY_CATS}
        for r in rows:
            gp = float(r['GP'])
            stats = {}
            for key, _, col, _ in FANTASY_CATS:
                per_game = pd.to_numeric(r.get(col), errors='coerce')
                per_game = 0.0 if pd.isna(per_game) else float(per_game)
                # PPP/SHP are stored as per-game rates alongside the _GP columns
                value = per_game * gp
                stats[key] = round(value, 1)
                totals[key] += value
            players.append({
                'name': r['name'],
                'team': r.get('team', ''),
                'pos': str(r.get('Pos', '')),
                'image': r.get('Image') or 'default_logo.png',
                'gp': round(gp, 1),
                'fp': round(float(r['FantasyPoints']), 1),
                'vorp': round(float(r['VORP']), 1),
                'stats': stats,
            })
        players.sort(key=lambda p: p['vorp'], reverse=True)
        return {
            'players': players,
            'count': len(players),
            'fp': round(sum(p['fp'] for p in players), 1),
            'vorp': round(sum(p['vorp'] for p in players), 1),
            'best_vorp': round(max([p['vorp'] for p in players], default=0.0), 1),
            'totals': {k: round(v, 1) for k, v in totals.items()},
        }

    a = side(pick(args.getlist('a')[:6]))
    b = side(pick(args.getlist('b')[:6]))

    # Category leagues are won category by category, so score them that way.
    cat_rows, a_wins, b_wins, ties = [], 0, 0, 0
    if league_type == 'categories':
        for key, label, _, higher in FANTASY_CATS:
            if key not in included:
                continue
            av, bv = a['totals'][key], b['totals'][key]
            if abs(av - bv) < 0.05:
                edge = None; ties += 1
            elif (av > bv) == higher:
                edge = 'a'; a_wins += 1
            else:
                edge = 'b'; b_wins += 1
            cat_rows.append({'key': key, 'label': label, 'a': av, 'b': bv,
                             'edge': edge, 'higher': higher})

    # Roster spots: whoever sends more bodies frees a spot, and that spot gets
    # filled off waivers at roughly replacement level (VORP 0).
    spare = a['count'] - b['count']

    if not a['count'] or not b['count']:
        winner = None
        headline = 'Add players to both sides'
        detail = 'Put at least one player on each side.'
    elif league_type == 'categories':
        winner = 'a' if a_wins > b_wins else ('b' if b_wins > a_wins else None)
        margin = abs(a_wins - b_wins)
        if winner is None:
            headline = f'Splits the categories {a_wins}-{b_wins}'
            detail = 'Nobody gains ground. Which categories you are already winning or already out of matters more here than the split.'
        else:
            headline = f'Side {winner.upper()} takes {max(a_wins, b_wins)} of {len(cat_rows)} categories'
            detail = ('One category in it. Look at which ones, not the count.'
                      if margin <= 1 else
                      'A comfortable win on count. Check that the categories you gain are ones you are actually close in.')
    else:
        gap = abs(a['vorp'] - b['vorp'])
        winner = 'a' if a['vorp'] > b['vorp'] else ('b' if b['vorp'] > a['vorp'] else None)
        # Judge the gap against the size of the deal. Sixty points between two
        # stars is noise; sixty points between two depth guys is a fleecing.
        scale = max(abs(a['vorp']), abs(b['vorp']), 1.0)
        pct = gap / scale * 100
        if pct < 8:
            headline = 'Close to even'
            detail = 'Too close to call on value. Decide it on what your roster needs.'
        elif pct < 20:
            headline = f'Side {winner.upper()} by {round(gap)} points of value'
            detail = 'A real but modest edge. Worth a point or two a week over the season.'
        else:
            headline = f'Side {winner.upper()} by {round(gap)} points of value'
            detail = 'That is a big gap. If you are on the wrong end of it, you had better be fixing a hole somewhere.'

    note = None
    if a['count'] and b['count'] and spare:
        # a['count'] is what Side A *receives*. Getting back fewer bodies means
        # sending more, which frees a roster spot for that manager.
        frees = 'A' if spare < 0 else 'B'
        n = abs(spare)
        spot = 'a roster spot' if n == 1 else f'{n} roster spots'
        note = (f'Side {frees} sends more bodies than it gets back and opens up {spot}. '
                f'Those get filled off waivers, and waiver guys are worth about zero here, '
                f'so quantity does not do much for you. The best player usually decides '
                f'these deals.')

    return jsonify({
        'a': a, 'b': b,
        'league_type': league_type,
        'categories': cat_rows,
        'cat_score': {'a': a_wins, 'b': b_wins, 'ties': ties},
        'winner': winner,
        'headline': headline,
        'detail': detail,
        'note': note,
    })


@app.route('/teams')
def teams_overview():
    selected_team = request.args.get('team')
    dfm = df_merged.copy()
    if 'Team' not in dfm.columns and 'team' in dfm.columns:
        dfm = dfm.rename(columns={'team': 'Team'})

    # pick a default team if none provided
    teams_available = dfm['Team'].dropna().unique().tolist()
    if not teams_available:
        return render_template('teams_overview.html',
                               team_name="",
                               team_logo="default_logo.png",
                               team_stats={},
                               leaderboard_data=[],
                               pts_projections=[],
                               top_team_projections={},
                               lowest_team_projections={},
                               league_average_projections=[],
                               fw_stats={}, def_stats={}, top_12_forwards={}, top_6_defensemen={},
                               total_team_pts_gp=0, fw_pts_gp=0, def_pts_gp=0,
                               top_12_fw_pts_gp=0, top_6_def_pts_gp=0,
                               total_team_rank=0, fw_rank=0, def_rank=0,
                               top_12_fw_rank=0, top_6_def_rank=0,
                               fw_rank_under_23=0, def_rank_under_23=0)

    if not selected_team or selected_team not in teams_available:
        selected_team = teams_available[0]

    # Build the per-year rate columns BEFORE slicing to a single team, otherwise
    # the slice is taken from a frame that does not yet have PT_Y1..PT_Y7.
    for y in range(1, 8):
        # If any season fields are missing (unlikely now), fall back to current-season per-game/GP
        if f'TOTPT_Y{y}' not in dfm.columns:
            dfm[f'TOTPT_Y{y}'] = (dfm['PTSTOT'] / dfm['GP2']).replace([np.inf, -np.inf], 0).fillna(0)
        if f'GPY{y}' not in dfm.columns:
            dfm[f'GPY{y}'] = dfm['GP2'].fillna(0)

        # PT_Y* is already a per-game rate because TOTPT_Y* = pts_pg_*
        dfm[f'PT_Y{y}'] = dfm[f'TOTPT_Y{y}']

    year_cols = [f'PT_Y{y}' for y in range(1, 8)]

    team_players = dfm[dfm['Team'] == selected_team]
    team_logo = team_players['Image'].values[0] if not team_players.empty and pd.notna(team_players['Image'].values[0]) else 'default_logo.png'

    team_stats = team_players[['GP2','GTOT','ATOT','PTSTOT','PIM']].sum().to_dict() if not team_players.empty else {}
    leaderboard = team_players[['link','name','fw_def','age','PTSTOT','GP2','GTOT','ATOT','PIM']].copy()
    leaderboard = leaderboard.sort_values(by='PTSTOT', ascending=False).round(2) if not team_players.empty else pd.DataFrame()
    leaderboard_data = leaderboard.to_dict(orient='records')

    pts_projections = team_players[year_cols].mean().round(3).tolist() if not team_players.empty else []

    # League-wide comparison. Each of these must be a 7-value series so it can be
    # plotted against Year 1..7 -- previously these were dicts of {team: scalar},
    # which drew three meaningless points on a seven-point axis.
    league_pts_projections = dfm.groupby('Team')[year_cols].mean()
    team_means = league_pts_projections.mean(axis=1)

    top_team_name = team_means.idxmax() if not team_means.empty else selected_team
    lowest_team_name = team_means.idxmin() if not team_means.empty else selected_team

    top_team_projections = league_pts_projections.loc[top_team_name].round(3).tolist()
    lowest_team_projections = league_pts_projections.loc[lowest_team_name].round(3).tolist()
    league_average_projections = league_pts_projections.mean(axis=0).round(3).tolist()

    # Team rankings by points/GP
    team_rankings = dfm.groupby('Team').agg({'PTSTOT':'sum','GP2':'sum','Image':'first'}).reset_index()
    team_rankings['PTSPERG'] = team_rankings['PTSTOT'] / team_rankings['GP2']
    team_rankings = team_rankings.sort_values(by='PTSPERG', ascending=False).round(3)
    team_rank = int(team_rankings.reset_index(drop=True).index[team_rankings['Team'] == selected_team][0]) + 1

    # --- Positional ranks -------------------------------------------------
    # The team page charts seven ranks. They used to be hardcoded to 0, which
    # drew every bar at full length. These compute them for real.
    def _rank_of(frame, team, top_n=None):
        """Rank every team by PTS/GP within `frame`, return (rank, pts_gp)."""
        if frame.empty:
            return 0, 0.0
        f = frame
        if top_n is not None:
            f = (f.sort_values('PTSTOT', ascending=False)
                   .groupby('Team', group_keys=False)
                   .head(top_n))
        agg = f.groupby('Team').agg({'PTSTOT': 'sum', 'GP2': 'sum'})
        agg = agg[agg['GP2'] > 0]
        if agg.empty or team not in agg.index:
            return 0, 0.0
        agg['PTSPERG'] = agg['PTSTOT'] / agg['GP2']
        order = agg['PTSPERG'].rank(ascending=False, method='min')
        return int(order.loc[team]), round(float(agg['PTSPERG'].loc[team]), 3)

    fw_frame = dfm[dfm['fw_def'] == 'FW']
    def_frame = dfm[dfm['fw_def'] == 'DEF']
    ages = pd.to_numeric(dfm.get('age'), errors='coerce')
    u23 = dfm[ages < 23]

    fw_rank, fw_pts_gp = _rank_of(fw_frame, selected_team)
    def_rank, def_pts_gp = _rank_of(def_frame, selected_team)
    top_12_fw_rank, top_12_fw_pts_gp = _rank_of(fw_frame, selected_team, top_n=12)
    top_6_def_rank, top_6_def_pts_gp = _rank_of(def_frame, selected_team, top_n=6)
    fw_rank_under_23, _ = _rank_of(u23[u23['fw_def'] == 'FW'], selected_team)
    def_rank_under_23, _ = _rank_of(u23[u23['fw_def'] == 'DEF'], selected_team)

    return render_template('teams_overview.html',
                           team_name=selected_team,
                           team_logo=team_logo,
                           team_stats=team_stats,
                           leaderboard_data=leaderboard_data,
                           pts_projections=pts_projections,
                           top_team_projections=top_team_projections,
                           lowest_team_projections=lowest_team_projections,
                           league_average_projections=league_average_projections,
                           top_team_name=top_team_name,
                           lowest_team_name=lowest_team_name,
                           teams_available=sorted(teams_available),
                           fw_stats={}, def_stats={}, top_12_forwards={}, top_6_defensemen={},
                           total_team_pts_gp=round(team_stats.get('PTSTOT',0)/team_stats.get('GP2',1), 3) if team_stats.get('GP2') else 0,
                           fw_pts_gp=fw_pts_gp, def_pts_gp=def_pts_gp,
                           top_12_fw_pts_gp=top_12_fw_pts_gp, top_6_def_pts_gp=top_6_def_pts_gp,
                           total_team_rank=team_rank,
                           fw_rank=fw_rank, def_rank=def_rank,
                           top_12_fw_rank=top_12_fw_rank, top_6_def_rank=top_6_def_rank,
                           fw_rank_under_23=fw_rank_under_23, def_rank_under_23=def_rank_under_23)

# =============================================================================
# NEW PAGES
# =============================================================================

# Categories surfaced on the leaders board: (key, label, column, per-game?)
LEADER_CATEGORIES = [
    ('PTS', 'Points',        'PTS_GP',        True),
    ('G',   'Goals',         'G_GP',          True),
    ('A',   'Assists',       'A_GP',          True),
    ('SOG', 'Shots',         'SOG_GP',        True),
    ('PPP', 'Power play pts','PPP_GP',        True),
    ('BLK', 'Blocks',        'BLK_GP',        True),
    ('HIT', 'Hits',          'HIT_GP',        True),
    ('PIM', 'Penalty mins',  'PIM_GP',        True),
]


def _leaders_frame():
    f = df_final_projections.copy()
    f['PPP_GP'] = pd.to_numeric(f['PPG'], errors='coerce').fillna(0) + \
                  pd.to_numeric(f['PPA'], errors='coerce').fillna(0)
    for _, _, col, _ in LEADER_CATEGORIES:
        f[col] = pd.to_numeric(f[col], errors='coerce').fillna(0.0)
    f['Pos'] = f['Pos'].astype(str)
    return f


@app.route('/leaders')
def leaders():
    """Top-ten boards per category for the coming season."""
    basis = request.args.get('basis', 'total')          # 'total' or 'per_game'
    pos_filter = (request.args.get('pos') or '').upper()
    team_filter = request.args.get('team') or ''

    f = _leaders_frame()

    if team_filter:
        f = f[f['team'] == team_filter]
    if pos_filter == 'F':
        f = f[~f['Pos'].str.contains('D', na=False)]
    elif pos_filter == 'D':
        f = f[f['Pos'].str.contains('D', na=False)]
    elif pos_filter in ('C', 'LW', 'RW'):
        f = f[f['Pos'].str.contains(pos_filter, na=False)]

    # Full 84 for everyone, matching the projections table and the trade
    # analyzer, so the same player shows the same total on every page.
    games = 84.0

    boards = []
    for key, label, col, _ in LEADER_CATEGORIES:
        vals = f[col] if basis == 'per_game' else f[col] * games
        board = pd.DataFrame({
            'name': f['name'], 'team': f['team'], 'pos': f['Pos'],
            'image': f['Image'], 'value': vals,
        }).sort_values('value', ascending=False).head(10)
        board['value'] = board['value'].round(2 if basis == 'per_game' else 0)
        peak = float(board['value'].max()) if not board.empty else 0.0
        board['share'] = (board['value'] / peak * 100).round(1) if peak else 0.0
        boards.append({'key': key, 'label': label,
                       'rows': board.to_dict(orient='records')})

    teams_list = sorted(x for x in df_final_projections['team'].dropna().unique())
    return render_template('leaders.html', boards=boards, teams_list=teams_list,
                           basis=basis, pos_filter=pos_filter, team_filter=team_filter)


@app.route('/compare')
def compare():
    players = sorted(df_projections['name'].dropna().unique().tolist())
    picked = [p for p in request.args.getlist('player') if p in set(players)]
    if not picked:
        seed = df_projections.sort_values('PTSTOT', ascending=False)['name'].head(2)
        picked = seed.tolist()
    return render_template('compare.html', players=players, picked=picked[:4])


@app.route('/api/compare')
def api_compare():
    """Seven-year curve plus headline totals for up to four players."""
    names = request.args.getlist('player')[:4]
    out = []
    for nm in names:
        rows = df_projections[df_projections['name'] == nm]
        if rows.empty:
            continue
        r = rows.iloc[0]

        def num(v, nd=2):
            v = pd.to_numeric(v, errors='coerce')
            return None if pd.isna(v) else round(float(v), nd)

        out.append({
            'name': nm,
            'team': r.get('team', ''),
            'pos': r.get('fw_def', ''),
            'age': num(r.get('age'), 1),
            'image': r.get('Image') or 'default_logo.png',
            'gp': num(r.get('GP2'), 0),
            'g': num(r.get('GTOT'), 0),
            'a': num(r.get('ATOT'), 0),
            'pts': num(r.get('PTSTOT'), 0),
            'pts_per': num(r.get('PTS_Per'), 3),
            'cap_hit': num(r.get('cap_hit'), 0),
            'contract': (r.get('contract') or ''),
            'history': [num(r.get('pts_pg_1'), 3), num(r.get('pts_pg_2'), 3)],
            'curve': [num(r.get(f'TOTPT_Y{y}'), 3) for y in range(1, 8)],
        })
    return jsonify({'players': out})


VALUE_SORTS = {
    'cost_per_point': ('cost_per_point', True,  '$ / point'),
    'index':          ('index',          False, 'Value index'),
    'cap_hit':        ('cap_hit',        False, 'Cap hit'),
    'points':         ('PTSTOT',         False, 'Projected points'),
    'games':          ('GP2',            False, 'Projected games'),
    'age':            ('age',            True,  'Age'),
    'expiry':         ('contract',       True,  'Contract expiry'),
    'name':           ('name',           True,  'Player'),
}


@app.route('/value')
def value():
    """Cap hit against projected production. Uses contract data that the site
    already stored but never showed."""
    v = df_projections.copy()
    v['cap_hit'] = pd.to_numeric(v['cap_hit'], errors='coerce')
    v['PTSTOT'] = pd.to_numeric(v['PTSTOT'], errors='coerce')
    v['age'] = pd.to_numeric(v['age'], errors='coerce')
    v['GP2'] = pd.to_numeric(v['GP2'], errors='coerce')
    v = v[(v['cap_hit'] > 0) & (v['PTSTOT'] > 0)]

    # The median is taken over the whole priced population, before filtering, so
    # the index means the same thing no matter how the table is sliced.
    v['cost_per_point'] = (v['cap_hit'] / v['PTSTOT']).round(0)
    league_median = float(v['cost_per_point'].median()) if not v.empty else 0.0
    v['index'] = (league_median / v['cost_per_point'] * 100).round(0)

    v['contract'] = v['contract'].fillna('').astype(str).replace({'nan': '', 'None': ''})

    def num_arg(key):
        raw = (request.args.get(key) or '').strip()
        if raw == '':
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    pos_filter = (request.args.get('pos') or '').upper()
    team_filter = request.args.get('team') or ''
    expiry = request.args.get('expiry') or ''
    age_min, age_max = num_arg('age_min'), num_arg('age_max')
    cap_min, cap_max = num_arg('cap_min'), num_arg('cap_max')   # in $M
    min_pts = num_arg('min_pts')

    if pos_filter in ('FW', 'DEF'):
        v = v[v['fw_def'] == pos_filter]
    if team_filter:
        v = v[v['team'] == team_filter]
    if expiry:
        # Contracts are stored as the expiring season, e.g. "27/28". Two-digit
        # seasons in this range sort correctly as plain strings.
        v = v[(v['contract'] != '') & (v['contract'] <= expiry)]
    if age_min is not None:
        v = v[v['age'] >= age_min]
    if age_max is not None:
        v = v[v['age'] <= age_max]
    if cap_min is not None:
        v = v[v['cap_hit'] >= cap_min * 1_000_000]
    if cap_max is not None:
        v = v[v['cap_hit'] <= cap_max * 1_000_000]
    if min_pts is not None:
        v = v[v['PTSTOT'] >= min_pts]

    sort_key = request.args.get('sort') or 'cost_per_point'
    if sort_key not in VALUE_SORTS:
        sort_key = 'cost_per_point'
    column, default_asc, _ = VALUE_SORTS[sort_key]
    direction = request.args.get('dir')
    ascending = default_asc if direction not in ('asc', 'desc') else (direction == 'asc')
    v = v.sort_values(column, ascending=ascending, kind='mergesort', na_position='last')

    matched = len(v)
    limit_raw = request.args.get('limit') or '300'
    limit = None if limit_raw == 'all' else max(int(limit_raw), 1) if limit_raw.isdigit() else 300
    shown = v if limit is None else v.head(limit)

    cols = ['name', 'team', 'fw_def', 'age', 'cap_hit', 'contract',
            'PTSTOT', 'GP2', 'cost_per_point', 'index', 'Image']
    rows = shown[cols].to_dict(orient='records')

    expiries = sorted(x for x in df_projections['contract'].dropna().astype(str).unique()
                      if x and x not in ('nan', 'None'))
    teams_list = sorted(x for x in df_projections['team'].dropna().unique())

    return render_template(
        'value.html',
        rows=rows,
        matched=matched,
        total_priced=len(df_projections[pd.to_numeric(df_projections['cap_hit'], errors='coerce') > 0]),
        median_cpp=round(league_median),
        sorts=VALUE_SORTS,
        sort_key=sort_key,
        direction='asc' if ascending else 'desc',
        limit=limit_raw,
        teams_list=teams_list,
        expiries=expiries,
        f={'pos': pos_filter, 'team': team_filter, 'expiry': expiry,
           'age_min': request.args.get('age_min', ''), 'age_max': request.args.get('age_max', ''),
           'cap_min': request.args.get('cap_min', ''), 'cap_max': request.args.get('cap_max', ''),
           'min_pts': request.args.get('min_pts', '')},
    )


@app.route('/healthz')
def healthz():
    """Quick self-check. Open /healthz in the browser to confirm which build is
    running and that JSON output is safe for this Flask install."""
    import flask as _flask
    probe = jsonify({'probe': float('nan')}).get_data(as_text=True)
    nan_safe = 'NaN' not in probe

    sample = None
    try:
        no_cap = df_projections[df_projections['cap_hit'].isna()]
        if not no_cap.empty:
            name = no_cap['name'].iloc[0]
            body = _player_payload(name)
            raw = body[0].get_data(as_text=True) if isinstance(body, tuple) else body.get_data(as_text=True)
            sample = {'player': name, 'parses_in_browser': 'NaN' not in raw and 'Infinity' not in raw}
    except Exception as exc:
        sample = {'error': f'{type(exc).__name__}: {exc}'}

    return jsonify({
        'build': KUBOTA_BUILD,
        'flask': getattr(_flask, '__version__', 'unknown'),
        'pandas': pd.__version__,
        'json_nan_safe': nan_safe,
        'database': os.path.basename(DB_PROD_PATH),
        'skaters_loaded': int(df_projections['name'].nunique()),
        'uncontracted_player_check': sample,
    })


@app.errorhandler(404)
def not_found(_e):
    return render_template('error.html', code=404,
                           heading="That page isn't here",
                           message="The link is probably out of date. Everything is "
                                   "still reachable from the menu up top."), 404


@app.errorhandler(500)
def server_error(_e):
    return render_template('error.html', code=500,
                           heading="Something broke on our end",
                           message="The page did not build. Try it again, and if it "
                                   "keeps happening drop us a line."), 500


@app.context_processor
def inject_nav():
    return dict(current_endpoint=(request.endpoint or ''))


@app.context_processor
def inject_team_rankings():
    dfm = df_merged.copy()
    if 'Team' not in dfm.columns and 'team' in dfm.columns:
        dfm = dfm.rename(columns={'team': 'Team'})
    # Ensure 'Image' exists
    if 'Image' not in dfm.columns:
        img_cols = [c for c in dfm.columns if c.lower().startswith('image')]
        if img_cols:
            dfm['Image'] = dfm[img_cols].bfill(axis=1).iloc[:, 0]
        else:
            dfm['Image'] = 'default_logo.png'

    team_rankings = dfm.groupby('Team').agg({'PTSTOT':'sum','GP2':'sum','Image':'first'}).reset_index()
    team_rankings['PTSPERG'] = team_rankings['PTSTOT'] / team_rankings['GP2']
    team_rankings = team_rankings.sort_values(by='PTSPERG', ascending=False).round(3)
    team_rankings['Rank'] = range(1, len(team_rankings) + 1)
    return dict(teams_ranked=team_rankings.to_dict(orient='records'))



if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
    #pass
