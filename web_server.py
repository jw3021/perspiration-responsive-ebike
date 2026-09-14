from flask import Flask, jsonify, render_template_string, request
import config

app = Flask(__name__)

# Global state
ride_active          = False
ride_mode            = "DATA_COLLECTION"  # "ACTUATION" or "DATA_COLLECTION"
last_ride_id         = "UNKNOWN"
sweat_reduction_active = False   # Set True by ebike_controller when ML triggers
sweat_triggered_at   = None      # ISO timestamp string of when actuation fired

# Live sensor data — updated each loop iteration by ebike_controller
live_data = {
    "cadence_rpm":   0.0,
    "torque_nm":     0.0,
    "temp_c":        0.0,
    "speed_kph":     0.0,
    "voltage_out_v": 1.0,
    "power_mode":    "LOW",   # "LOW" or "HIGH" — reflects active power band
}

# Demo override — toggled from /display without needing a formal ride
demo_power_high = False

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

@app.route('/live', methods=['GET'])
def live():
    """Returns current sensor snapshot as JSON — polled by the /display dashboard."""
    return jsonify(live_data)

@app.route('/demo_power', methods=['POST'])
def demo_power():
    """Toggles the demo power override between LOW and HIGH — called from /display."""
    global demo_power_high
    demo_power_high = not demo_power_high
    print(f"\n[DEMO] Power mode set to {'HIGH (sweat reduction)' if demo_power_high else 'LOW (normal)'}")
    return jsonify({"demo_power_high": demo_power_high})

DISPLAY_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <title>E-Bike Live</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background: #0d0d0d;
            color: #fff;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            height: 100vh;
            display: flex;
            flex-direction: column;
            padding: 16px;
            gap: 14px;
        }
        #header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-shrink: 0;
        }
        h1 {
            font-size: 20px;
            font-weight: 700;
            letter-spacing: 0.5px;
            color: #ddd;
        }
        .badge {
            background: #1c1c1c;
            border-radius: 10px;
            padding: 8px 20px;
            text-align: center;
            border: 1px solid #2a2a2a;
        }
        .badge-label {
            font-size: 10px;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            color: #666;
            margin-bottom: 2px;
        }
        .badge-value {
            font-size: 22px;
            font-weight: 700;
            color: #f39c12;
        }
        #power-btn {
            width: 100%;
            padding: 12px 24px;
            border-radius: 10px;
            border: none;
            font-size: 15px;
            font-weight: 800;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            cursor: pointer;
            transition: transform 0.1s, opacity 0.1s;
            flex-shrink: 0;
        }
        #power-btn:active { transform: scale(0.98); opacity: 0.85; }
        #power-btn.low  { background: linear-gradient(135deg, #1a1f2e, #2e3550); color: #5B9BD5; border: 1px solid #5B9BD5; }
        #power-btn.high { background: linear-gradient(135deg, #1a2e1a, #2a4a2a); color: #2ECC71; border: 1px solid #2ECC71; }
        #charts {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 14px;
            flex: 1;
            min-height: 0;
        }
        .chart-card {
            background: #141414;
            border-radius: 12px;
            padding: 16px 16px 12px 16px;
            display: flex;
            flex-direction: column;
            border: 1px solid #1e1e1e;
        }
        .chart-title {
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: #555;
            margin-bottom: 10px;
            flex-shrink: 0;
        }
        .chart-wrap {
            flex: 1;
            position: relative;
            min-height: 0;
        }
    </style>
</head>
<body>
    <div id="header">
        <h1>E-Bike &mdash; Live Sensor Data</h1>
        <div class="badge">
            <div class="badge-label">Ambient Temp</div>
            <div class="badge-value" id="temp-val">--&nbsp;&deg;C</div>
        </div>
    </div>

    <button id="power-btn" class="low" onclick="togglePower()">
        &#9654; LOW POWER MODE &mdash; tap to activate sweat reduction
    </button>

    <div id="charts">
        <div class="chart-card">
            <div class="chart-title">Sensor Inputs</div>
            <div class="chart-wrap"><canvas id="leftChart"></canvas></div>
        </div>
        <div class="chart-card">
            <div class="chart-title">Motor Output</div>
            <div class="chart-wrap"><canvas id="rightChart"></canvas></div>
        </div>
    </div>

    <script>
        const N = 30;
        const emptyWindow = () => Array(N).fill(null);

        const cadenceData = emptyWindow();
        const torqueData  = emptyWindow();
        const speedData   = emptyWindow();
        const voltageData = emptyWindow();
        const labels      = Array(N).fill('');

        const baseOpts = {
            animation: false,
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    labels: { color: '#bbb', font: { size: 13, weight: '600' }, padding: 20, boxWidth: 14 }
                },
                tooltip: { enabled: false }
            }
        };

        function yAxis(color, label, min, max, position, drawGrid) {
            return {
                type: 'linear',
                position,
                min,
                max,
                title: {
                    display: true,
                    text: label,
                    color,
                    font: { size: 12, weight: 'bold' }
                },
                ticks: { color, font: { size: 11 }, maxTicksLimit: 6 },
                grid: {
                    color: drawGrid ? 'rgba(255,255,255,0.05)' : 'transparent',
                    drawBorder: false
                },
                border: { color: 'rgba(255,255,255,0.1)' }
            };
        }

        function dataset(label, data, color, yAxisID) {
            return {
                label,
                data,
                borderColor: color,
                backgroundColor: color.replace('rgb', 'rgba').replace(')', ',0.08)'),
                borderWidth: 2.5,
                pointRadius: 0,
                tension: 0.35,
                fill: true,
                yAxisID
            };
        }

        // LEFT — Sensor Inputs (Cadence + Torque)
        const leftChart = new Chart(document.getElementById('leftChart'), {
            type: 'line',
            data: {
                labels,
                datasets: [
                    dataset('Cadence (RPM)', cadenceData, 'rgb(243,156,18)',  'yCadence'),
                    dataset('Torque (Nm)',   torqueData,  'rgb(231,76,60)',   'yTorque'),
                ]
            },
            options: {
                ...baseOpts,
                scales: {
                    x: { ticks: { display: false }, grid: { color: 'rgba(255,255,255,0.04)' } },
                    yCadence: yAxis('rgb(243,156,18)', 'Cadence (RPM)', 0, 120, 'left',  true),
                    yTorque:  yAxis('rgb(231,76,60)',  'Torque (Nm)',   0, 60,  'right', false),
                }
            }
        });

        // RIGHT — Motor Output (Speed + Voltage)
        const rightChart = new Chart(document.getElementById('rightChart'), {
            type: 'line',
            data: {
                labels,
                datasets: [
                    dataset('Speed (km/h)',     speedData,   'rgb(52,152,219)',  'ySpeed'),
                    dataset('Motor Voltage (V)', voltageData, 'rgb(46,204,113)', 'yVoltage'),
                ]
            },
            options: {
                ...baseOpts,
                scales: {
                    x: { ticks: { display: false }, grid: { color: 'rgba(255,255,255,0.04)' } },
                    ySpeed:   yAxis('rgb(52,152,219)',  'Speed (km/h)',      0,   30,  'left',  true),
                    yVoltage: yAxis('rgb(46,204,113)', 'Motor Voltage (V)', 1.0, 4.5, 'right', false),
                }
            }
        });

        function push(arr, val) { arr.shift(); arr.push(val); }

        function updatePowerBtn(mode) {
            const btn = document.getElementById('power-btn');
            if (mode === 'HIGH') {
                btn.className = 'high';
                btn.innerHTML = '&#9646;&#9646; SWEAT REDUCTION &mdash; tap to return to low power';
            } else {
                btn.className = 'low';
                btn.innerHTML = '&#9654; LOW POWER MODE &mdash; tap to activate sweat reduction';
            }
        }

        async function togglePower() {
            try {
                await fetch('/demo_power', { method: 'POST' });
                poll(); // immediate refresh so button state updates without waiting
            } catch(e) {}
        }

        async function poll() {
            try {
                const r = await fetch('/live');
                const d = await r.json();

                push(cadenceData, d.cadence_rpm);
                push(torqueData,  d.torque_nm);
                push(speedData,   d.speed_kph);
                push(voltageData, d.voltage_out_v);

                document.getElementById('temp-val').textContent =
                    d.temp_c > 0 ? d.temp_c.toFixed(1) + ' \u00b0C' : '-- \u00b0C';

                updatePowerBtn(d.power_mode);

                leftChart.update('none');
                rightChart.update('none');
            } catch(e) { /* ignore mid-demo network blips */ }
        }

        poll();
        setInterval(poll, 500);
    </script>
</body>
</html>"""

@app.route('/display')
def display():
    """Full-screen live chart dashboard — open on a presentation screen."""
    return DISPLAY_TEMPLATE

if __name__ == '__main__':
    print("=" * 60)
    print("Starting E-Bike Web Server...")
    print("Open your phone browser and go to your Pi's IP:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=False)
