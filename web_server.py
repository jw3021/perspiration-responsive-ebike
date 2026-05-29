from flask import Flask, jsonify, render_template_string, request
import config

app = Flask(__name__)

# Global state
ride_active          = False
ride_mode            = "DATA_COLLECTION"  # "ACTUATION" or "DATA_COLLECTION"
last_ride_id         = "UNKNOWN"
sweat_reduction_active = False   # Set True by ebike_controller when ML triggers
sweat_triggered_at   = None      # ISO timestamp string of when actuation fired

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>E-Bike Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            text-align: center;
            margin: 0;
            padding: 20px;
            background-color: #121212;
            color: #ffffff;
        }
        h1 { margin-bottom: 6px; }
        .subtitle { color: #888; font-size: 13px; margin-bottom: 24px; }

        .status-box {
            border-radius: 10px;
            padding: 14px 20px;
            margin-bottom: 28px;
            font-size: 17px;
            font-weight: bold;
            letter-spacing: 0.3px;
        }
        .status-idle       { background: #1e1e1e; color: #888; }
        .status-actuation  { background: #1a2e1a; color: #2ECC71; border: 1px solid #2ECC71; }
        .status-motortest  { background: #2e1e0a; color: #E67E22; border: 1px solid #E67E22; }
        .status-datacoll   { background: #1a1f2e; color: #5B9BD5; border: 1px solid #5B9BD5; }

        .mode-label {
            font-size: 11px;
            font-weight: normal;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            opacity: 0.7;
            margin-bottom: 4px;
        }

        .btn {
            padding: 18px 20px;
            font-size: 18px;
            border-radius: 10px;
            cursor: pointer;
            border: none;
            font-weight: 800;
            width: 100%;
            display: block;
            margin: 10px auto;
            box-shadow: 0 4px 10px rgba(0,0,0,0.4);
            transition: transform 0.1s, opacity 0.1s;
        }
        .btn:active { transform: scale(0.97); opacity: 0.85; }

        .mode-section {
            margin-bottom: 8px;
        }
        .mode-header {
            font-size: 11px;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            color: #666;
            margin-bottom: 6px;
        }

        .btn-actuation {
            background: linear-gradient(135deg, #27AE60, #1E8449);
            color: white;
        }
        .btn-motortest {
            background: linear-gradient(135deg, #E67E22, #A04000);
            color: white;
        }
        .btn-datacoll {
            background: linear-gradient(135deg, #2E4482, #1a2a5e);
            color: white;
        }
        .btn-stop {
            background: linear-gradient(135deg, #C0392B, #922B21);
            color: white;
            margin-top: 20px;
        }

        .divider {
            border: none;
            border-top: 1px solid #2a2a2a;
            margin: 18px 0;
        }

        .note { font-size: 13px; color: #888; padding: 12px 6px; font-style: italic; }

        .actuation-box {
            display: none;
            background: linear-gradient(135deg, #1a0a2e, #2d0a3e);
            border: 2px solid #9B59B6;
            border-radius: 12px;
            padding: 18px 20px;
            margin-bottom: 20px;
            animation: pulse-border 2s infinite;
        }
        .actuation-box.visible { display: block; }
        .actuation-title {
            font-size: 13px;
            font-weight: 800;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: #9B59B6;
            margin-bottom: 6px;
        }
        .actuation-body {
            font-size: 16px;
            font-weight: bold;
            color: #ffffff;
            margin-bottom: 4px;
        }
        .actuation-time {
            font-size: 12px;
            color: #aaa;
        }
        @keyframes pulse-border {
            0%   { box-shadow: 0 0 0px #9B59B6; }
            50%  { box-shadow: 0 0 14px #9B59B6; }
            100% { box-shadow: 0 0 0px #9B59B6; }
        }

        .survey-btn {
            background-color: #2a2a2a;
            color: white;
            margin-bottom: 8px;
            font-size: 16px;
            font-weight: 600;
            padding: 14px 20px;
        }
    </style>
</head>
<body>
    <h1>E-Bike Dashboard</h1>
    <div class="subtitle">Raspberry Pi Motor Controller</div>

    <div class="status-box status-idle" id="status-box">
        <div class="mode-label" id="status-mode-label">MODE</div>
        <div id="status-text">No ride active</div>
    </div>

    <!-- ML Actuation notification box (hidden until controller fires) -->
    <div class="actuation-box" id="actuation-box">
        <div class="actuation-title">⚡ Sweat Reduction Activated</div>
        <div class="actuation-body">ML model detected sweat onset — motor now in sweat reduction mode</div>
        <div class="actuation-time" id="actuation-time"></div>
    </div>

    <!-- Ride start controls -->
    <div id="ride-controls">

        <div class="mode-section">
            <div class="mode-header">ML Actuation Ride</div>
            <button class="btn btn-actuation" onclick="startRide('ACTUATION')">
                ▶ START ACTUATION RIDE
            </button>
        </div>

        <div class="mode-header" style="color:#444; font-size:13px; margin: 4px 0;">— or —</div>

        <div class="mode-section">
            <div class="mode-header">Motor Test (Forced Sweat Reduction)</div>
            <button class="btn btn-motortest" onclick="startRide('MOTOR_TEST')">
                ▶ START MOTOR TEST
            </button>
        </div>

        <div class="mode-header" style="color:#444; font-size:13px; margin: 4px 0;">— or —</div>

        <div class="mode-section">
            <div class="mode-header">Data Collection Ride</div>
            <button class="btn btn-datacoll" onclick="startRide('DATA_COLLECTION')">
                ▶ START DATA COLLECTION RIDE
            </button>
        </div>

        <hr class="divider">

        <button class="btn btn-stop" onclick="stopRide()">■ END RIDE</button>

        <p class="note">
            After pressing START, switch to the HDrop App and leave it open so data scraping works.
        </p>
    </div>

    <!-- Post-ride survey -->
    <div id="survey" style="display: none; margin-top: 20px;">
        <h2>Post-Ride Survey</h2>
        <p>How intensely did you sweat?</p>
        <div style="display: flex; flex-direction: column; gap: 8px;">
            <button class="btn survey-btn" onclick="submitSurvey(1)">1 — Completely Dry</button>
            <button class="btn survey-btn" onclick="submitSurvey(2)">2 — Lightly Sweating</button>
            <button class="btn survey-btn" onclick="submitSurvey(3)">3 — Moderately Sweaty</button>
            <button class="btn survey-btn" onclick="submitSurvey(4)">4 — Very Sweaty</button>
            <button class="btn survey-btn" onclick="submitSurvey(5)">5 — Max Effort (Dripping)</button>
        </div>
    </div>

    <script>
        function updateStatus(active, mode) {
            const box   = document.getElementById('status-box');
            const label = document.getElementById('status-mode-label');
            const text  = document.getElementById('status-text');

            box.className = 'status-box';

            if (!active) {
                box.classList.add('status-idle');
                label.innerText = 'MODE';
                text.innerText  = 'No ride active';
                return;
            }

            if (mode === 'ACTUATION') {
                box.classList.add('status-actuation');
                label.innerText = 'ACTUATION MODE';
                text.innerText  = 'ML model running — sweat onset monitoring active';
            } else if (mode === 'MOTOR_TEST') {
                box.classList.add('status-motortest');
                label.innerText = 'MOTOR TEST MODE';
                text.innerText  = 'Sweat reduction forced ON — no ML required';
            } else {
                box.classList.add('status-datacoll');
                label.innerText = 'DATA COLLECTION MODE';
                text.innerText  = 'Recording ride data — no ML actuation';
            }
        }

        function startRide(mode) {
            // Reset actuation box for the new ride
            document.getElementById('actuation-box').classList.remove('visible');
            document.getElementById('actuation-time').innerText = '';

            fetch('/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({mode: mode})
            })
            .then(r => r.json())
            .then(data => {
                updateStatus(data.active, data.mode);
                document.getElementById('survey').style.display = 'none';
            });
        }

        // Poll actuation status every 3 seconds during an actuation ride
        function pollActuation() {
            fetch('/actuation_status')
                .then(r => r.json())
                .then(data => {
                    if (data.active) {
                        const box = document.getElementById('actuation-box');
                        box.classList.add('visible');
                        const t = new Date(data.triggered_at);
                        document.getElementById('actuation-time').innerText =
                            'Triggered at ' + t.toLocaleTimeString();
                    }
                })
                .catch(() => {}); // ignore poll errors mid-ride
        }
        setInterval(pollActuation, 3000);

        function stopRide() {
            fetch('/stop', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    updateStatus(data.active, null);
                    document.getElementById('ride-controls').style.display = 'none';
                    document.getElementById('survey').style.display = 'block';
                });
        }

        function submitSurvey(score) {
            fetch('/survey', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({score: score})
            })
            .then(r => r.json())
            .then(() => {
                document.getElementById('survey').innerHTML =
                    "<h2 style='color:#2ecc71'>Survey Saved</h2><p>Data synced to Supabase.</p>";
            });
        }
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/start', methods=['POST'])
def start_ride():
    global ride_active, ride_mode, sweat_reduction_active, sweat_triggered_at
    data = request.get_json(silent=True) or {}
    ride_mode              = data.get('mode', 'DATA_COLLECTION')
    ride_active            = True
    sweat_reduction_active = False   # reset for each new ride
    sweat_triggered_at     = None
    print(f"\n[ACTION] Ride STARTED — mode: {ride_mode}")
    return jsonify({"status": "success", "active": ride_active, "mode": ride_mode})

@app.route('/notify_actuation', methods=['POST'])
def notify_actuation():
    """Called by ebike_controller when the ML model sustains a sweat onset prediction."""
    global sweat_reduction_active, sweat_triggered_at
    from datetime import datetime
    if not sweat_reduction_active:          # only latch once per ride
        sweat_reduction_active = True
        sweat_triggered_at     = datetime.now().isoformat()
        print(f"\n[ML ACTUATION] Sweat reduction mode ACTIVATED at {sweat_triggered_at}")
    return jsonify({"status": "ok"})

@app.route('/actuation_status', methods=['GET'])
def actuation_status():
    """Polled by the dashboard UI to show the actuation notification box."""
    return jsonify({"active": sweat_reduction_active, "triggered_at": sweat_triggered_at})

@app.route('/stop', methods=['POST'])
def stop_ride():
    global ride_active
    ride_active = False
    print(f"\n[ACTION] Ride STOPPED — was in {ride_mode} mode")
    return jsonify({"status": "success", "active": ride_active})

@app.route('/mode', methods=['GET'])
def get_mode():
    """Polled by ebike_controller to know which mode to run in."""
    return jsonify({"mode": ride_mode, "active": ride_active})

@app.route('/survey', methods=['POST'])
def submit_survey():
    data  = request.json
    score = data.get('score')
    print(f"\n[SURVEY] Score: {score}/5 for ride: {last_ride_id}")
    try:
        from supabase import create_client
        if hasattr(config, 'SUPABASE_URL') and hasattr(config, 'SUPABASE_KEY'):
            client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
            client.table("ride_surveys").insert({
                "ride_id": last_ride_id,
                "sweat_perception_score": score
            }).execute()
            print("[SURVEY] Uploaded to Supabase.")
    except Exception as e:
        print(f"[SURVEY Error] {e}")
    return jsonify({"status": "success"})

@app.route('/status', methods=['GET'])
def status():
    return jsonify({"active": ride_active, "mode": ride_mode})

if __name__ == '__main__':
    print("=" * 60)
    print("Starting E-Bike Web Server...")
    print("Open your phone browser and go to your Pi's IP:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=False)
