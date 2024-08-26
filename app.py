from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import pandas as pd
import numpy as np
import random
import stripe
import io
import csv
import unicodedata

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Stripe keys
app.config['STRIPE_PUBLIC_KEY'] = 'your_stripe_publishable_key'
app.config['STRIPE_SECRET_KEY'] = 'your_stripe_secret_key'

stripe.api_key = app.config['STRIPE_SECRET_KEY']

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Load the CSV data
df_projections = pd.read_csv('/Users/brennan/Kubota Website/KUBOTAPROJECTIONS.csv')
df_comps = pd.read_csv('/Users/brennan/Kubota Website/KUBOTACOMPS.csv')
df_logos = pd.read_csv('/Users/brennan/Kubota Website/playerteams.csv')
df_final_projections = pd.read_csv('/Users/brennan/Kubota Website/FINALNHLPLAYERPROJECTIONS.csv')
df_merged = df_projections.merge(df_logos[['URL', 'Team', 'Image']], left_on='link', right_on='URL', how='left')


df_final_projections['Pos'] = df_final_projections['Pos'].replace('W', 'RW')  # Default 'W' to 'RW'
df_final_projections['Pos'] = df_final_projections['Pos'].replace('F', 'C')   # Default 'F' to 'C'

# Dummy user data
users = {
    'user@example.com': {'password': 'password', 'premium': True},
    'nonpremium@example.com': {'password': 'password', 'premium': False}
}

class User(UserMixin):
    def __init__(self, email):
        self.id = email
        self.email = email
        self.premium = users[email]['premium']

@login_manager.user_loader
def load_user(email):
    if email not in users:
        return None
    return User(email)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/forecasts')
def forecasts():
    selected_columns = [
        'name', 'fw_def', 'age', 'GP2', 'GTOT', 'ATOT', 'PTSTOT', 'PIM2', 'G_per', 'A_per', 'PTS_Per'
    ]
    # Round values to 2 decimal places and sort by PTS2 column
    df_selected = df_projections[selected_columns].copy()
    df_selected = df_selected[~np.isinf(df_selected['PTSTOT'])]
    df_selected = df_selected.round(2)
    df_selected = df_selected.sort_values(by='PTSTOT', ascending=False)
    
    columns = df_selected.columns.tolist()
    data = df_selected.to_dict(orient='records')
    
    return render_template('forecasts.html', columns=columns, data=data)

@app.route('/currentyear')
def currentyear():
    selected_columns = [
        'Link', 'name', 'team', 'Image', 'Pos', 'Age', 'GPNEW', 
        'G_GP', 'A_GP', 'PTS_GP', 'SOG_GP', 'PIM_GP', 'PLUSMINUS_GP', 
        'PPG', 'PPA', 'SHG', 'SHA', 'BLK_GP', 'HIT_GP', 'FOL_GP', 'FOW_GP'
    ]
    df_selected = df_final_projections[selected_columns].copy()
    df_selected = df_selected.round(2)
    data = df_selected.to_dict(orient='records')
    
    return render_template('currentyear.html', data=data)

@app.route('/calculate_fantasy_points', methods=['POST'])
def calculate_fantasy_points():
    try:
        # Get the league type (points or categories)
        league_type = request.form.get('league_type', 'points')

        # Get the settings
        g_points = float(request.form.get('g_points', 6))
        a_points = float(request.form.get('a_points', 4))
        sog_points = float(request.form.get('sog_points', 0.9))
        pim_points = float(request.form.get('pim_points', 0))
        plusminus_points = float(request.form.get('plusminus_points', 2))
        ppg_points = float(request.form.get('ppg_points', 2))
        ppa_points = float(request.form.get('ppa_points', 2))
        shg_points = float(request.form.get('shg_points', 0))
        sha_points = float(request.form.get('sha_points',0))
        blk_points = float(request.form.get('blk_points', 1))
        hit_points = float(request.form.get('hit_points', 0))
        fol_points = float(request.form.get('fol_points', 0))
        fow_points = float(request.form.get('fow_points', 0))

        # Apply season length
        df_selected = df_final_projections.copy()
        if request.form.get('season_length') == '82':
            df_selected['GP'] = 82
        else:
            df_selected['GP'] = df_selected['GPNEW']

        # Points League: Calculate fantasy points
        if league_type == 'points':
            df_selected['FantasyPoints'] = (
                df_selected['G_GP'] * df_selected['GP'] * g_points +
                df_selected['A_GP'] * df_selected['GP'] * a_points +
                df_selected['SOG_GP'] * df_selected['GP'] * sog_points +
                df_selected['PIM_GP'] * df_selected['GP'] * pim_points +
                df_selected['PLUSMINUS_GP'] * df_selected['GP'] * plusminus_points +
                df_selected['PPG'] * df_selected['GP'] * ppg_points +
                df_selected['PPA'] * df_selected['GP'] * ppa_points +
                df_selected['SHG'] * df_selected['GP'] * shg_points +
                df_selected['SHA'] * df_selected['GP'] * sha_points +
                df_selected['BLK_GP'] * df_selected['GP'] * blk_points +
                df_selected['HIT_GP'] * df_selected['GP'] * hit_points +
                df_selected['FOL_GP'] * df_selected['GP'] * fol_points +
                df_selected['FOW_GP'] * df_selected['GP'] * fow_points
            )
        # Categories League: Calculate standard deviation above/below mean
        elif league_type == 'categories':
            category_columns = ['G_GP', 'A_GP', 'SOG_GP', 'PIM_GP', 'PLUSMINUS_GP', 'PPG', 'PPA', 'SHG', 'SHA', 'BLK_GP', 'HIT_GP', 'FOL_GP', 'FOW_GP']
            df_selected['FantasyPoints'] = 0  # Initialize the column
            
            for column, multiplier in zip(category_columns, [
                g_points, a_points, sog_points, pim_points, plusminus_points, ppg_points, ppa_points,
                shg_points, sha_points, blk_points, hit_points, fol_points, fow_points
            ]):
                if multiplier != 0:
                    mean = df_selected[column].mean()
                    std_dev = df_selected[column].std()
                    df_selected['FantasyPoints'] += (df_selected[column] - mean) / std_dev

        # Sort by FantasyPoints descending
        df_selected = df_selected.sort_values(by='FantasyPoints', ascending=False)

        # Generate HTML for table rows
        rows_html = ''
        for index, row in df_selected.iterrows():
            rows_html += f'<tr>'
            rows_html += f'<td>{row["name"]}</td>'
            rows_html += f'<td>{row["team"]}</td>'
            rows_html += f'<td>{row["Pos"]}</td>'
            rows_html += f'<td>{round(row["GP"], 2)}</td>'
            rows_html += f'<td>{round(row["G_GP"] * row["GP"], 2)}</td>'
            rows_html += f'<td>{round(row["A_GP"] * row["GP"], 2)}</td>'
            rows_html += f'<td>{round(row["PTS_GP"] * row["GP"], 2)}</td>'
            rows_html += f'<td>{round(row["SOG_GP"] * row["GP"], 2)}</td>'
            rows_html += f'<td>{round(row["PIM_GP"] * row["GP"], 2)}</td>'
            rows_html += f'<td>{round(row["PLUSMINUS_GP"] * row["GP"], 2)}</td>'
            rows_html += f'<td>{round(row["PPG"] * row["GP"], 2)}</td>'
            rows_html += f'<td>{round(row["PPA"] * row["GP"], 2)}</td>'
            rows_html += f'<td>{round(row["SHG"] * row["GP"], 2)}</td>'
            rows_html += f'<td>{round(row["SHA"] * row["GP"], 2)}</td>'
            rows_html += f'<td>{round(row["BLK_GP"] * row["GP"], 2)}</td>'
            rows_html += f'<td>{round(row["HIT_GP"] * row["GP"], 2)}</td>'
            rows_html += f'<td>{round(row["FOL_GP"] * row["GP"], 2)}</td>'
            rows_html += f'<td>{round(row["FOW_GP"] * row["GP"], 2)}</td>'
            rows_html += f'<td>{round(row["FantasyPoints"], 2)}</td>'
            rows_html += f'</tr>'

        return rows_html

    except Exception as e:
        print(f"Error: {e}")
        return "An error occurred during the calculation.", 500
    
@app.route('/export_csv', methods=['POST'])
def export_csv():
    try:
        # Retrieve the table data from the request
        table_data = request.json.get('tableData', [])

        # Create a CSV file in memory
        csv_data = io.StringIO()
        writer = csv.writer(csv_data)

        # Write the table data to the CSV
        for row in table_data:
            writer.writerow(row)

        csv_data.seek(0)

        # Send the CSV file as a download with the desired filename
        return send_file(
            io.BytesIO(csv_data.getvalue().encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name='kubota_hockey_2024_2025.csv'  # Set the desired filename here
        )

    except Exception as e:
        print(f"Error: {e}")
        return "An error occurred during the CSV export.", 500

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/player')
@login_required
def player_page():
    if not current_user.premium:
        flash('You need a premium membership to access this page.', 'danger')
        return redirect(url_for('upgrade'))
    players = df_projections['name'].tolist()
    random_player = request.args.get('player', random.choice(players))
    return render_template('player.html', players=players, random_player=random_player)

@app.route('/get_player_data', methods=['POST'])
@login_required
def get_player_data():
    if not current_user.premium:
        return jsonify({'error': 'Premium membership required'}), 403

    player_name = request.form['player_name']
    projection_data = df_projections[df_projections['name'] == player_name].to_dict(orient='records')
    if not projection_data:
        return jsonify({'error': 'No data found for this player.'}), 404

    anchor = df_projections[df_projections['name'] == player_name]['anchor'].values[0]
    comps_data = df_comps[df_comps['anchor'] == anchor].fillna(0).to_dict(orient='records')  # Replace NA with 0
    image_link = df_logos[df_logos['URL'] == anchor]['Image'].values[0]
    return jsonify({'projection': projection_data, 'comps': comps_data,'image_link': image_link})

@app.route('/player_comps')
def player_comps():
    return render_template('player_comps.html')

@app.route('/api/player_comps', methods=['GET'])
def api_player_comps():
    draw = int(request.args.get('draw', 1))
    start = int(request.args.get('start', 0))
    length = int(request.args.get('length', 15))
    search_value = request.args.get('search[value]', '')

    # Join df_comps with df_projections on the 'anchor' column
    merged_df = df_comps.merge(df_projections[['anchor', 'name']], left_on='anchor', right_on='anchor', how='left')

    if search_value:
        merged_df = merged_df[merged_df['Comparables'].str.contains(search_value, case=False, na=False)]

    # Sort by SCORE
    merged_df = merged_df.sort_values(by='SCORE', ascending=False)

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
    
    if selected_team is None or selected_team not in df_merged['Team'].unique():
        selected_team = df_merged['Team'].iloc[0]
    
    team_players = df_merged[df_merged['Team'] == selected_team]
    
    # Safely get the team logo
    team_logo = team_players['Image'].values[0] if not team_players.empty and team_players['Image'].values[0] else 'default_logo.png'
    
    # Calculate team stats
    team_stats = team_players[['GP2', 'GTOT', 'ATOT', 'PTSTOT', 'PIM']].sum().to_dict() if not team_players.empty else {}
    leaderboard = team_players[['link', 'name', 'fw_def', 'age', 'PTSTOT', 'GP2', 'GTOT', 'ATOT', 'PIM']].copy()
    leaderboard = leaderboard.sort_values(by='PTSTOT', ascending=False).round(2) if not team_players.empty else pd.DataFrame()
    leaderboard_data = leaderboard.to_dict(orient='records')
    
    # Calculate projections correctly by dividing TOTPT_Y1 (and so on) by GPY1
    def calculate_pts_per_game(row, y):
        return row[f'TOTPT_Y{y}'] / row[f'GPY{y}'] if row[f'GPY{y}'] > 0 else 0

    for y in range(1, 8):
        df_merged[f'PT_Y{y}'] = df_merged.apply(lambda row: calculate_pts_per_game(row, y), axis=1)
    
    pts_projections = team_players[[f'PT_Y{y}' for y in range(1, 8)]].mean().tolist() if not team_players.empty else []
    
    # League-wide projections (same method)
    league_pts_projections = df_merged.groupby('Team')[[f'TOTPT_Y{y}' for y in range(1, 8)]].sum()
    league_games_played = df_merged.groupby('Team')[[f'GPY{y}' for y in range(1, 8)]].sum()
    
    for y in range(1, 8):
        league_pts_projections[f'PT_Y{y}'] = league_pts_projections[f'TOTPT_Y{y}'] / league_games_played[f'GPY{y}']

    top_team_projections = league_pts_projections[[f'PT_Y{y}' for y in range(1, 8)]].max().tolist()
    lowest_team_projections = league_pts_projections[[f'PT_Y{y}' for y in range(1, 8)]].min().tolist()
    league_average_projections = league_pts_projections[[f'PT_Y{y}' for y in range(1, 8)]].mean().tolist()
    
    # Calculate stats for FWs and DEFs for the selected team
    forwards = team_players[team_players['fw_def'] == 'FW']
    defensemen = team_players[team_players['fw_def'] == 'DEF']

    top_12_forwards = forwards.nlargest(12, 'PTSTOT')[['GP2', 'GTOT', 'ATOT', 'PTSTOT', 'PIM']].sum().to_dict() if not forwards.empty else {}
    top_6_defensemen = defensemen.nlargest(6, 'PTSTOT')[['GP2', 'GTOT', 'ATOT', 'PTSTOT', 'PIM']].sum().to_dict() if not defensemen.empty else {}

    fw_stats = forwards[['GP2', 'GTOT', 'ATOT', 'PTSTOT', 'PIM']].sum().to_dict() if not forwards.empty else {}
    def_stats = defensemen[['GP2', 'GTOT', 'ATOT', 'PTSTOT', 'PIM']].sum().to_dict() if not defensemen.empty else {}

    # Safely calculate PTS/GP for each category
    total_team_pts_gp = team_stats.get('PTSTOT', 0) / team_stats.get('GP2', 1)
    fw_pts_gp = fw_stats.get('PTSTOT', 0) / fw_stats.get('GP2', 1)
    def_pts_gp = def_stats.get('PTSTOT', 0) / def_stats.get('GP2', 1)
    top_12_fw_pts_gp = top_12_forwards.get('PTSTOT', 0) / top_12_forwards.get('GP2', 1)
    top_6_def_pts_gp = top_6_defensemen.get('PTSTOT', 0) / top_6_defensemen.get('GP2', 1)

    # Calculate PTS/GP for all teams in each category
    team_pts_gp = df_merged.groupby('Team').apply(lambda x: x['PTSTOT'].sum() / x['GP2'].sum() if x['GP2'].sum() > 0 else 0)
    fw_pts_gp_league = df_merged[df_merged['fw_def'] == 'FW'].groupby('Team').apply(lambda x: x['PTSTOT'].sum() / x['GP2'].sum() if x['GP2'].sum() > 0 else 0)
    def_pts_gp_league = df_merged[df_merged['fw_def'] == 'DEF'].groupby('Team').apply(lambda x: x['PTSTOT'].sum() / x['GP2'].sum() if x['GP2'].sum() > 0 else 0)

    top_12_fw_pts_gp_league = df_merged[df_merged['fw_def'] == 'FW'].groupby('Team').apply(lambda x: x.nlargest(12, 'PTSTOT')[['PTSTOT', 'GP2']].sum()['PTSTOT'] / x.nlargest(12, 'PTSTOT')[['PTSTOT', 'GP2']].sum()['GP2'] if x.nlargest(12, 'PTSTOT')[['PTSTOT', 'GP2']].sum()['GP2'] > 0 else 0)
    top_6_def_pts_gp_league = df_merged[df_merged['fw_def'] == 'DEF'].groupby('Team').apply(lambda x: x.nlargest(6, 'PTSTOT')[['PTSTOT', 'GP2']].sum()['PTSTOT'] / x.nlargest(6, 'PTSTOT')[['PTSTOT', 'GP2']].sum()['GP2'] if x.nlargest(6, 'PTSTOT')[['PTSTOT', 'GP2']].sum()['GP2'] > 0 else 0)

    # Ranking for players under the age of 23 by position
    players_under_23 = df_merged[df_merged['age'] < 23]
    fw_pts_gp_under_23_league = players_under_23[players_under_23['fw_def'] == 'FW'].groupby('Team').apply(lambda x: x['PTSTOT'].sum() / x['GP2'].sum() if x['GP2'].sum() > 0 else 0)
    def_pts_gp_under_23_league = players_under_23[players_under_23['fw_def'] == 'DEF'].groupby('Team').apply(lambda x: x['PTSTOT'].sum() / x['GP2'].sum() if x['GP2'].sum() > 0 else 0)

    # Rank each team by PTS/GP
    total_team_rank = team_pts_gp.rank(ascending=False)[selected_team]
    fw_rank = fw_pts_gp_league.rank(ascending=False)[selected_team]
    def_rank = def_pts_gp_league.rank(ascending=False)[selected_team]
    top_12_fw_rank = top_12_fw_pts_gp_league.rank(ascending=False)[selected_team]
    top_6_def_rank = top_6_def_pts_gp_league.rank(ascending=False)[selected_team]
    fw_rank_under_23 = fw_pts_gp_under_23_league.rank(ascending=False)[selected_team]
    def_rank_under_23 = def_pts_gp_under_23_league.rank(ascending=False)[selected_team]

    return render_template('teams_overview.html', 
                           team_name=selected_team, 
                           team_logo=team_logo,
                           team_stats=team_stats,
                           leaderboard_data=leaderboard_data,
                           pts_projections=pts_projections,
                           top_team_projections=top_team_projections,
                           lowest_team_projections=lowest_team_projections,
                           league_average_projections=league_average_projections,
                           fw_stats=fw_stats,
                           def_stats=def_stats,
                           top_12_forwards=top_12_forwards,
                           top_6_defensemen=top_6_defensemen,
                           total_team_pts_gp=total_team_pts_gp,
                           fw_pts_gp=fw_pts_gp,
                           def_pts_gp=def_pts_gp,
                           top_12_fw_pts_gp=top_12_fw_pts_gp,
                           top_6_def_pts_gp=top_6_def_pts_gp,
                           total_team_rank=int(total_team_rank),
                           fw_rank=int(fw_rank),
                           def_rank=int(def_rank),
                           top_12_fw_rank=int(top_12_fw_rank),
                           top_6_def_rank=int(top_6_def_rank),
                           fw_rank_under_23=int(fw_rank_under_23),
                           def_rank_under_23=int(def_rank_under_23))



@app.context_processor
def inject_team_rankings():
    # Group by team and sum the points
    team_rankings = df_merged.groupby('Team').agg({
        'PTS': 'sum',
        'Image': 'first'  # Get the first image for each team
    }).reset_index()
    
    # Sort teams by total points in descending order
    team_rankings = team_rankings.sort_values(by='PTS', ascending=False)
    
    # Add a rank column
    team_rankings['Rank'] = range(1, len(team_rankings) + 1)
    
    # Convert to list of dictionaries for easy template rendering
    teams_ranked = team_rankings.to_dict(orient='records')
    
    return dict(teams_ranked=teams_ranked)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if email in users and users[email]['password'] == password:
            user = User(email)
            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('home'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if email in users:
            flash('Email already registered.', 'danger')
        else:
            users[email] = {'password': password, 'premium': False}
            flash('Registration successful. Please log in.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/upgrade')
@login_required
def upgrade():
    if request.method == 'POST':
        try:
            # Create a new Stripe checkout session
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': 'Premium Membership',
                        },
                        'unit_amount': 999,  # Price in cents
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=url_for('upgrade_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=url_for('upgrade', _external=True),
            )
            return redirect(session.url, code=303)
        except Exception as e:
            flash(str(e), 'danger')
            return redirect(url_for('upgrade'))

    return render_template('upgrade.html', key=app.config['STRIPE_PUBLIC_KEY'])

@login_required
def upgrade_success():
    session_id = request.args.get('session_id')
    session = stripe.checkout.Session.retrieve(session_id)

    # Update user to premium in your database
    current_user.premium = True
    # Add logic to save this change to your database

    flash('Your account has been upgraded to premium!', 'success')
    return redirect(url_for('home'))


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)