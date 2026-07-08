# Week 3 Report – Swarm Telemetry and Monitoring

## Overview
Implemented multi‑drone telemetry support for the Ground Control Station (GCS). The changes enable:
- Inclusion of a `drone_id` field in every telemetry packet.
- Per‑drone telemetry logging to separate files.
- A combined swarm log that can be retrieved via a new HTTP endpoint.
- Updated documentation for running the GCS in WSL.

## Files Added
- **telemetry_logger.py** – Helper module that creates the log directory, appends per‑drone JSON lines, and combines logs.

## Files Modified
### `telemetry_server.py`
```diff
@@ -1,5 +1,6 @@
 import asyncio
 import json
+import telemetry_logger
 from quart import Quart, websocket, request
@@
 async def emit_telemetry(data):
     json_message = json.dumps(data)
     print(f"[DEBUG] Emitting telemetry: {json_message}")
@@
     else:
         loop.run_until_complete(broadcast_queue.put(json_message))
+    telemetry_logger.append_log(data.get("drone_id", "unknown"), data)
@@
-@app.before_serving
-async def startup():
-    app.add_background_task(broadcast_worker)
-    #app.add_background_task(generate_fake_telemetry) #this is to test the server, websocket with fake data
+@app.route("/export_swarm_log", methods=["GET"]) 
+async def export_swarm_log():
+    combined_path = telemetry_logger.combine_logs()
+    try:
+        with open(combined_path, "r", encoding="utf-8") as f:
+            content = f.read()
+    except Exception as e:
+        return {"status": "error", "message": str(e)}
+    return {"status": "ok", "combined_log": content}
+
+
+@app.before_serving
+async def startup():
+    app.add_background_task(broadcast_worker)
+    #app.add_background_task(generate_fake_telemetry) #this is to test the server, websocket with fake data
```

### `swarm_documentation.md`
Added a **Running the GCS in WSL** section describing installation of WSL, Python dependencies, and how to start the server.

## Verification
- **Automated**: `curl -X POST http://127.0.0.1:5000/send_telemetry` with different `drone_id`s confirms logs are created and WebSocket broadcasts both streams.
- **Manual**: Running the server inside WSL shows separate UI telemetry panels per drone and the `/export_swarm_log` endpoint returns a combined log.

## Log Directory Structure
```
logs/
  drone_1_telemetry.log
  drone_2_telemetry.log
  swarm_telemetry_combined.log
```
All log files are standard JSON‑lines for easy parsing.

*Report generated on 2026‑06‑23.*
