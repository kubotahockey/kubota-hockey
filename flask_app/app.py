#!/usr/bin/env python3
from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd
import numpy as np
from sqlalchemy import create_engine
import io, csv, random
import math
from pathlib import Path
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# =============================================================================
# DB CONFIG (cross-platform: works on Windows & Linux)
# =============================================================================
# Resolve DB path relative to this file so it works on both Windows and Linux
BASE_DIR = Path(__file__).resolve().parent
DB_PROD_PATH = str((BASE_DIR / "database" / "Kubota_Website_PROD.db").resolve())

# Allow override via env if you ever need it
import os
DB_PROD_PATH = os.getenv("KUBOTA_DB_PATH", DB_PROD_PATH)

engine = create_engine(f"sqlite:///{DB_PROD_PATH}")

# Table names used below
TABLE_FINAL        = "FINAL_PROJECTIONS"
TABLE_ROSTER_CLEAN = "1YR_FINAL_ROSTER_CLEAN"
TABLE_COMPS_1YR    = "1YR_FINAL_COMPS"
TABLE_COMPS_DRAFT  = "DRAFT_PROJECTIONS_COMPS"

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


LAST_UPDATE = "Aug 28, 2025"

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

# GPNEW = 82 * GP_Percent (fallback 82)
if "GPNEW" not in stats.columns:
    if "GP_Percent" in stats.columns:
        stats["GPNEW"] = (82 * pd.to_numeric(stats["GP_Percent"], errors="coerce")).clip(0, 82)
    else:
        stats["GPNEW"] = 82.0
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

# GP2 for totals = gp_3 (fallback 82)
R["GP2"] = R.get("gp_3", 82).fillna(82).clip(lower=0, upper=82)

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

# (Optional, handy for your table bars that use season 1 totals)
# df_comps['GPproj'] = df_comps.get('gp_3', 0).fillna(0.0)
# df_comps['Gproj']  = df_comps.get('gpg_3', 0).fillna(0.0)  * df_comps['GPproj']
# df_comps['Aproj']  = df_comps.get('apg_3', 0).fillna(0.0)  * df_comps['GPproj']
# df_comps['PIMproj']= df_comps.get('pimpg_3',0).fillna(0.0) * df_comps['GPproj']
# =============================================================================
# ROUTES
# =============================================================================
@app.route('/')
def home():
    return render_template('index.html')

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
    return render_template('currentyear.html', data=data)


@app.route('/calculate_fantasy_points', methods=['POST'])
def calculate_fantasy_points():
    try:
        # --- Inputs ---
        league_type = (request.form.get('league_type') or 'points').strip().lower()
        position_grouping = (request.form.get('position_grouping') or 'split').strip().lower()  # 'split' or 'fw_def'
        teams = int(request.form.get('teams', 12))
        util_starters = int(request.form.get('util_starters', 0))
        util_total = teams * max(util_starters, 0)

        # Roster slots (starters only)
        if position_grouping == 'split':
            slots_LW = int(request.form.get('lw_starters', 2))
            slots_RW = int(request.form.get('rw_starters', 2))
            slots_C  = int(request.form.get('c_starters', 2))
            slots_D  = int(request.form.get('d_starters', 4))
            roster_counts = {
                'LW': teams * max(slots_LW, 0),
                'RW': teams * max(slots_RW, 0),
                'C' : teams * max(slots_C,  0),
                'D' : teams * max(slots_D,  0),
            }
            bench_total = teams * max(int(request.form.get('bench_split', 0)), 0)
        else:  # 'fw_def'
            slots_F  = int(request.form.get('fw_starters', 6))
            slots_D  = int(request.form.get('def_starters', 4))
            roster_counts = {
                'F': teams * max(slots_F, 0),
                'D': teams * max(slots_D, 0),
            }
            bench_total = teams * max(int(request.form.get('bench_fwdef', 0)), 0)

        # DAILY-LINEUP streaming factor (0..1). 0.6 ≈ typical nightly streaming.
        bench_weight = float(request.form.get('bench_weight', 0.6))
        stream_total = int(math.floor(bench_total * max(min(bench_weight, 1.0), 0.0)))

        scoring_settings = {
            'G': float(request.form.get('g_points', 6)),
            'A': float(request.form.get('a_points', 4)),
            'SOG': float(request.form.get('sog_points', 0.9)),
            'PIM': float(request.form.get('pim_points', 0)),
            'PLUSMINUS': float(request.form.get('plusminus_points', 2)),
            'PPG': float(request.form.get('ppg_points', 2)),
            'PPA': float(request.form.get('ppa_points', 2)),
            'PPP': float(request.form.get('ppp_points', 0)),  # keep 0 in points leagues to avoid double counting PP
            'SHG': float(request.form.get('shg_points', 0)),
            'SHA': float(request.form.get('sha_points', 0)),
            'SHP': float(request.form.get('shp_points', 0)),
            'BLK': float(request.form.get('blk_points', 0.5)),
            'HIT': float(request.form.get('hit_points', 0)),
            'FOL': float(request.form.get('fol_points', 0)),
            'FOW': float(request.form.get('fow_points', 0)),
        }
        defensive_points_multiplier = float(request.form.get('defensive_points', 0))

        # --- Data ---
        df_selected = df_final_projections.copy()

        # Season length
        season_length = request.form.get('season_length')
        df_selected['GP'] = 82 if season_length == '82' else df_selected['GPNEW']

        # Convenience totals
        df_selected['PPP'] = df_selected['PPG'] + df_selected['PPA']
        df_selected['SHP'] = df_selected['SHG'] + df_selected['SHA']

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
            df_selected['FantasyPoints'] = (
                df_selected['G_GP'] * df_selected['GP'] * scoring_settings['G'] +
                df_selected['A_GP'] * df_selected['GP'] * scoring_settings['A'] +
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
            cat_cols = [
                'G_GP','A_GP','SOG_GP','PIM_GP','PLUSMINUS_GP',
                'PPG','PPA','PPP','SHG','SHA','SHP','BLK_GP','HIT_GP','FOL_GP','FOW_GP'
            ]
            df_selected['FantasyPoints'] = 0.0
            for c in cat_cols:
                total_col = c + '_Total'
                df_selected[total_col] = df_selected[c] * df_selected['GP']
                m = df_selected[total_col].mean()
                s = df_selected[total_col].std()
                key = c.replace('_GP', '')
                mult = scoring_settings.get(key, 0)
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

        # --- Roster selection: POS -> UTIL -> STREAM (daily-lineup impact) ---
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

        # --- Replacement baselines from ACTUAL rostered set (POS + UTIL + STREAM) ---
        rostered_df = df_selected.loc[df_selected['Rostered']]
        baselines = {}
        for grp, sub in rostered_df.groupby('PosGroup'):
            # Replacement = worst of the rostered at that position (includes UTIL/STREAM spillover)
            baselines[grp] = float(sub['FantasyPoints'].min()) if not sub.empty else 0.0

        df_selected['AvgPosFP'] = df_selected['PosGroup'].map(lambda g: baselines.get(g, 0.0)).fillna(0.0)

        # --- VORP ---
        df_selected['VORP'] = df_selected['FantasyPoints'] - df_selected['AvgPosFP']

        # Sort by VORP (or by 'FantasyPoints' if preferred)
        df_selected = df_selected.sort_values(by='VORP', ascending=False)

        # --- Build rows (with data-key for sorting) ---
        rows = []
        rank = 0
        for _, row in df_selected.iterrows():
            rank += 1
            rows.append(
                '<tr>'
                f'<td>{rank}</td>'
                f'<td data-key="name">{row["name"]}</td>'
                f'<td data-key="team">{row["team"]}</td>'
                f'<td data-key="Pos">{row["Pos"].replace("LW","Left Wing").replace("RW","Right Wing").replace("C","Center").replace("D","Defense")}</td>'
                f'<td data-key="GP">{round(row["GP"], 2)}</td>'
                f'<td data-key="G_GP">{round(row["G_GP"] * row["GP"], 2)}</td>'
                f'<td data-key="A_GP">{round(row["A_GP"] * row["GP"], 2)}</td>'
                f'<td data-key="PTS_GP">{round(row["PTS_GP"] * row["GP"], 2)}</td>'
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

    except Exception as e:
        return f"An error occurred during the calculation: {str(e)}", 500

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
    player_name = request.form['player_name']

    # Use df_projections (roster-driven)
    rows = df_projections[df_projections['name'] == player_name]
    if rows.empty:
        return jsonify({'error': 'No data found for this player.'}), 404

    projection_data = rows.to_dict(orient='records')

    # Anchor/link for comps + image comes from df_projections['link']
    anchor = rows['link'].iloc[0] if 'link' in rows.columns else ""

    # Comps joined on anchor (target_player in DB)
    comps_data = df_comps[df_comps['anchor'] == anchor].fillna(0).to_dict(orient='records')

    # Image via df_logos (built from df_projections)
    try:
        image_link = df_logos.loc[df_logos['URL'] == anchor, 'Image'].iloc[0]
    except Exception:
        image_link = ''

    return jsonify({'projection': projection_data, 'comps': comps_data, 'image_link': image_link})

@app.route('/player_comps')
def player_comps():
    return render_template('player_comps.html')

@app.route('/api/player_comps', methods=['GET'])
def api_player_comps():
    draw = int(request.args.get('draw', 1))
    start = int(request.args.get('start', 0))
    length = int(request.args.get('length', 15))
    search_value = request.args.get('search[value]', '')

    merged_df = df_comps.merge(df_final_projections[['Link','name']], left_on='anchor', right_on='Link', how='left')
    if search_value:
        merged_df = merged_df[merged_df['Comparables'].str.contains(search_value, case=False, na=False)]
    merged_df = merged_df.sort_values(by='SCORE', ascending=False)
    merged_df['SCORE'] = pd.to_numeric(merged_df['SCORE'], errors='coerce').fillna(0).round(0)

    total_records = len(merged_df)
    filtered_comps = merged_df.iloc[start:start + length].to_dict(orient='records')

    return jsonify({
        'draw': draw,
        'recordsTotal': total_records,
        'recordsFiltered': total_records,
        'data': filtered_comps
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

    team_players = dfm[dfm['Team'] == selected_team]
    team_logo = team_players['Image'].values[0] if not team_players.empty and pd.notna(team_players['Image'].values[0]) else 'default_logo.png'

    team_stats = team_players[['GP2','GTOT','ATOT','PTSTOT','PIM']].sum().to_dict() if not team_players.empty else {}
    leaderboard = team_players[['link','name','fw_def','age','PTSTOT','GP2','GTOT','ATOT','PIM']].copy()
    leaderboard = leaderboard.sort_values(by='PTSTOT', ascending=False).round(2) if not team_players.empty else pd.DataFrame()
    leaderboard_data = leaderboard.to_dict(orient='records')

    for y in range(1, 8):
        # If any season fields are missing (unlikely now), fall back to current-season per-game/GP
        if f'TOTPT_Y{y}' not in dfm.columns:
            dfm[f'TOTPT_Y{y}'] = (dfm['PTSTOT'] / dfm['GP2']).replace([np.inf, -np.inf], 0).fillna(0)
        if f'GPY{y}' not in dfm.columns:
            dfm[f'GPY{y}'] = dfm['GP2'].fillna(0)
    
        # PT_Y* is already a per-game rate because TOTPT_Y* = pts_pg_*
        dfm[f'PT_Y{y}'] = dfm[f'TOTPT_Y{y}']

    pts_projections = team_players[[f'PT_Y{y}' for y in range(1, 8)]].mean().tolist() if not team_players.empty else []

    # League-wide comparison
    league_pts_projections = dfm.groupby('Team')[[f'PT_Y{y}' for y in range(1, 8)]].mean()
    top_team_projections = league_pts_projections.mean(axis=1).nlargest(3).round(2).to_dict()
    lowest_team_projections = league_pts_projections.mean(axis=1).nsmallest(3).round(2).to_dict()
    league_average_projections = league_pts_projections.mean(axis=0).round(2).tolist()

    # Team rankings by points/GP
    team_rankings = dfm.groupby('Team').agg({'PTSTOT':'sum','GP2':'sum','Image':'first'}).reset_index()
    team_rankings['PTSPERG'] = team_rankings['PTSTOT'] / team_rankings['GP2']
    team_rankings = team_rankings.sort_values(by='PTSPERG', ascending=False).round(3)
    team_rank = int(team_rankings.reset_index(drop=True).index[team_rankings['Team'] == selected_team][0]) + 1

    return render_template('teams_overview.html',
                           team_name=selected_team,
                           team_logo=team_logo,
                           team_stats=team_stats,
                           leaderboard_data=leaderboard_data,
                           pts_projections=pts_projections,
                           top_team_projections=top_team_projections,
                           lowest_team_projections=lowest_team_projections,
                           league_average_projections=league_average_projections,
                           fw_stats={}, def_stats={}, top_12_forwards={}, top_6_defensemen={},
                           total_team_pts_gp=team_stats.get('PTSTOT',0)/team_stats.get('GP2',1) if team_stats else 0,
                           fw_pts_gp=0, def_pts_gp=0,
                           top_12_fw_pts_gp=0, top_6_def_pts_gp=0,
                           total_team_rank=team_rank,
                           fw_rank=0, def_rank=0,
                           top_12_fw_rank=0, top_6_def_rank=0,
                           fw_rank_under_23=0, def_rank_under_23=0)

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
    pass
