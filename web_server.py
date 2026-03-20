from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

# Global state to track ride status
ride_active = False

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
            margin-top: 50px; 
            background-color: #121212; 
            color: #ffffff; 
        }
        .btn { 
            padding: 20px 40px; 
            font-size: 24px; 
            border-radius: 12px; 
            cursor: pointer; 
            border: none; 
            font-weight: 800; 
            width: 85%; 
            display: block; 
            margin: 20px auto; 
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
            transition: transform 0.1s;
        }
        .btn:active { transform: scale(0.95); }
        .start { background-color: #2ECC71; color: white; }
        .stop { background-color: #E74C3C; color: white; }
        .status { font-size: 22px; margin-bottom: 40px; font-weight: bold; }
        .note { font-size: 16px; color: #aaaaaa; padding: 20px; font-style: italic; }
    </style>
</head>
<body>
    <h1>E-Bike Dashboard</h1>
    
    <div class="status" id="status-text" style="color: #aaaaaa;">Ride Status: NOT STARTED</div>
    
    <button class="btn start" onclick="startRide()">START RIDE</button>
    <button class="btn stop" onclick="stopRide()">END RIDE</button>
    
    <p class="note">
        ⚠️ After pressing START, immediately switch to the HDrop App and leave it open so data scraping works!
    </p>

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
                    alert("✅ Ride Started! Switch to the HDrop app right now.");
                });
        }
        
        function stopRide() {
            fetch('/stop', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    updateStatus(data.active);
                    alert("🛑 Ride Ended!");
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
