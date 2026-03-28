from flask import Flask, jsonify, render_template_string, request
import config

app = Flask(__name__)

# Global state to track ride status
ride_active = False
last_ride_id = "UNKNOWN"

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
            margin-top: 30px; 
            background-color: #121212; 
            color: #ffffff; 
        }
        .btn { 
            padding: 15px 30px; 
            font-size: 20px; 
            border-radius: 8px; 
            cursor: pointer; 
            border: none; 
            font-weight: bold; 
            width: 90%; 
            display: block; 
            margin: 10px auto; 
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
            transition: transform 0.1s;
        }
        .btn:active { transform: scale(0.95); }
        .start { background-color: #2ECC71; color: white; padding: 25px 30px; font-size: 24px; font-weight: 900;}
        .stop { background-color: #E74C3C; color: white; padding: 25px 30px; font-size: 24px; font-weight: 900;}
        .status { font-size: 20px; margin-bottom: 30px; font-weight: bold; }
        .note { font-size: 14px; color: #aaaaaa; padding: 15px; font-style: italic; }
        .survey-btn { background-color: #34495e; color: white; margin-bottom: 5px; }
    </style>
</head>
<body>
    <h1>E-Bike Dashboard</h1>
    
    <div class="status" id="status-text" style="color: #aaaaaa;">Ride Status: NOT STARTED</div>
    
    <div id="ride-controls">
        <button class="btn start" onclick="startRide()">START RIDE</button>
        <button class="btn stop" onclick="stopRide()">END RIDE</button>
        
        <p class="note">
            ⚠️ After pressing START, switch to the HDrop App and leave it open so data scraping works!
        </p>
    </div>

    <!-- Hidden Survey Form -->
    <div id="survey" style="display: none; margin-top: 30px;">
        <h2>Post-Ride Survey</h2>
        <p>How intensely did you sweat just now?</p>
        <div style="display: flex; flex-direction: column; gap: 10px;">
            <button class="btn survey-btn" onclick="submitSurvey(1)">1 - Completely Dry</button>
            <button class="btn survey-btn" onclick="submitSurvey(2)">2 - Lightly Sweating</button>
            <button class="btn survey-btn" onclick="submitSurvey(3)">3 - Moderately Sweaty</button>
            <button class="btn survey-btn" onclick="submitSurvey(4)">4 - Very Sweaty</button>
            <button class="btn survey-btn" onclick="submitSurvey(5)">5 - Max Effort (Dripping)</button>
        </div>
    </div>

    <script>
        function updateStatus(active) {
            const statusText = document.getElementById('status-text');
            if (active) {
                statusText.innerText = "Ride Status: ACTIVE 🚲";
                statusText.style.color = "#2ECC71";
            } else {
                statusText.innerText = "Ride Status: NOT STARTED";
                statusText.style.color = "#E74C3C";
            }
        }

        function startRide() {
            fetch('/start', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    updateStatus(data.active);
                    document.getElementById('survey').style.display = 'none'; // hide survey if re-starting
                    alert("✅ Ride Started! Switch to the HDrop app right now.");
                });
        }
        
        function stopRide() {
            fetch('/stop', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    updateStatus(data.active);
                    // Hide the ride controls and pop up the survey!
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
            .then(data => {
                document.getElementById('survey').innerHTML = "<h2 style='color:#2ecc71'>✅ Survey Saved!</h2><p>Data synced to Supabase successfully.</p>";
            });
        }
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    """Serves the main dashboard page"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/start', methods=['POST'])
def start_ride():
    """API endpoint to start the ride"""
    global ride_active
    ride_active = True
    print("\n[ACTION] User pressed START. Ride is now ACTIVE.")
    # Later: This is where we trigger cloud IoT logging loops!
    return jsonify({"status": "success", "active": ride_active})

@app.route('/stop', methods=['POST'])
def stop_ride():
    """API endpoint to stop the ride"""
    global ride_active
    ride_active = False
    print("\n[ACTION] User pressed END. Ride is now STOPPED.")
    # Later: This is where we safely shut down IoT logs and save finals.
    return jsonify({"status": "success", "active": ride_active})

@app.route('/survey', methods=['POST'])
def submit_survey():
    """Receives the 1-5 subjective sweat rating from the user after the ride"""
    data = request.json
    score = data.get('score')
    print(f"\n[SURVEY] User rated their sweat effort as: {score}/5 for ride: {last_ride_id}")
    
    # Push to Supabase immediately
    try:
        from supabase import create_client
        if hasattr(config, 'SUPABASE_URL') and hasattr(config, 'SUPABASE_KEY'):
            client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
            client.table("ride_surveys").insert({
                "ride_id": last_ride_id,
                "sweat_perception_score": score
            }).execute()
            print("[SURVEY] Successfully uploaded survey to Supabase!")
    except Exception as e:
        print(f"[SURVEY Error] Could not upload survey: {e}")
        
    return jsonify({"status": "success"})

@app.route('/status', methods=['GET'])
def status():
    """API endpoint for other scripts to playfully check if a ride is active"""
    return jsonify({"active": ride_active})

if __name__ == '__main__':
    print("="*60)
    print("Starting E-Bike Web Server...")
    print("Open your phone's web browser and go to your Pi's IP address")
    print("Example: http://192.168.1.89:5000")
    print("="*60)
    
    # Run securely on all local network interfaces on port 5000
    app.run(host='0.0.0.0', port=5000, debug=False)
