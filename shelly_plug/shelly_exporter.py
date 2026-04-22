from flask import Flask, Response
import requests

app = Flask(__name__)

SHELLY_IP = "192.168.1.87"
PORT = "9101"


@app.route("/metrics")
def metrics():
    try:
        r = requests.get(f"http://{SHELLY_IP}/rpc/Shelly.GetStatus", timeout=2).json()
        data = r["switch:0"]

        power = data.get("apower", 0)
        voltage = data.get("voltage", 0)
        current = data.get("current", 0)

        return Response(
            f"""
# HELP shelly_power Power in watts
# TYPE shelly_power gauge
shelly_power {power}

# HELP shelly_voltage Voltage
# TYPE shelly_voltage gauge
shelly_voltage {voltage}

# HELP shelly_current Current
# TYPE shelly_current gauge
shelly_current {current}
""",
            mimetype="text/plain"
        )
    except Exception as e:
        return Response(f"# error {e}", mimetype="text/plain")

app.run(host="0.0.0.0", port=PORT)
