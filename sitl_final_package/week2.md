# Week 2 Swarm Flight System Documentation

This document serves as the complete documentation of the work completed during Week 2 to set up a Multi-Drone SITL environment, implement backend connection management, and build a color-coded Ground Control Station (GCS) telemetry dashboard.

---

## 📋 1. Project Specifications & Deliverables

* **Target Setup**: Connect to and control 2 to 5 simulated drones concurrently (defaulting to 3).
* **Network & Swarm Mapping**:
  * `drone_1` -> `udp:127.0.0.1:14551` (SysID 1)
  * `drone_2` -> `udp:127.0.0.1:14552` (SysID 2)
  * `drone_3` -> `udp:127.0.0.1:14553` (SysID 3)
  * `drone_4` -> `udp:127.0.0.1:14554` (SysID 4)
  * `drone_5` -> `udp:127.0.0.1:14555` (SysID 5)
* **Start Coordinates**: Islamabad (Base Lat=`33.6844`, Lon=`73.0479`, Alt=`540m`) with a symmetric **triangular (V-wedge) formation offset** (spacing of 15m) to prevent collisions and maintain structural formation.
* **Basic Swarm Mission**: Drones execute triangular formation trajectories concurrently, report independent telemetry logs, map positions in real-time, and land/disarm cleanly.

---

## 🛠️ 2. Detailed Code Modifications & Rationale

Four key components of the codebase were modified to support the multi-drone architecture:

### A. Swarm Simulator Startup Script
* **File**: `sitl_final_package/start_sitl.sh`
* **Modifications**:
  1. Added **directory resolution** (`cd "$(dirname "$0")"`) to guarantee execution in the correct workspace.
  2. Fixed **PATH escaping** in WSL by wrapping exports in double quotes (`export PATH="$PATH:..."`).
  3. Forced **non-interactive shell mode** (`export SITL_RITW_TERMINAL="sh"`) to prevent GUI/xterm popups in headless environments.
  4. Configured **daemon mode** (`--mavproxy-args="--daemon"`) on MAVProxy so instances launched in the background via `nohup` do not close upon receiving EOF on standard input.
  5. Changed redirection to write logs to native `/tmp/` to bypass write permission conflicts on mounted Windows drives.

### B. Swarm Mission Orchestrator
* **File**: `sitl_final_package/mavlink_integration/main.py`
* **Modifications**:
  1. Converted `run_drone_mission` to run on a separate OS-level thread using `asyncio.to_thread`. This prevents connection blocking (e.g., waiting for drone heartbeats) from locking up the main asyncio event loop.
  2. Implemented a **GPS & EKF Alignment Wait Loop** prior to requesting the flight mode change. Because ArduPilot rejects a `GUIDED` mode request until its position estimation is fully initialized, this loop waits for alignment before arming, ensuring the mode commands are accepted.
  3. Swarmed flight waypoints dynamically with coordinate offsets relative to each drone's index.

### C. SITL Connection Adapter
* **File**: `sitl_final_package/mavlink_integration/sitl_adapter.py`
* **Modifications**:
  1. Appended `drone_id` to the telemetry payload posted to the web server, enabling the backend database and registry to route packets.
  2. Isolated flight track exports so that each drone writes to its own file (e.g. `logs/drone_N_flight_path.csv` and `logs/drone_N_flight_path.geojson`).
  3. Clamped the relative altitude to `max(0.0, relative_alt)` to prevent telemetry displays from showing negative altitudes when a drone lands on ground terrain that is lower than the home launch position.
  4. Added a **socket buffer draining routine** at the start of `log_status()` to flush pending packages, ensuring fresh attitude values, and exported the drone's true GPS heading (`pos.hdg`) to prevent plane icons from freezing northwards.

### D. Ground Control Station UI Dashboard
* **File**: `sitl_final_package/mavlink_integration/index.html`
* **Modifications**:
  1. Refactored the dashboard sidebar to display a dynamic tabbed registry (`DRONE SWARM REGISTRY`), rendering color-coded icons and telemetry states individually for up to 5 drones.
  2. Modified map marker layers to display and update flight tracks individually using Leaflet polylines.
  3. Added frontend clamping (`Math.max(0.0, alt)`) to display neat `0.0m` values in the UI upon landing.

---

## 🏃 3. Run & Execution Guide

Always execute commands inside your WSL terminal as user **`immad_baber`** to ensure full access to the required libraries.

### Step 1: Terminate Existing Background Tasks
```bash
killall -9 arducopter mavproxy.py xterm python3
```

### Step 2: Start the Swarm Simulators
Open terminal tab 1 and launch 5 drones:
```bash
su - immad_baber
cd /mnt/d/gcs_s2025/gcs_s2025/sitl_final_package
bash start_sitl.sh 5
```

### Step 3: Run the Telemetry Dashboard Server
Open terminal tab 2:
```bash
su - immad_baber
cd /mnt/d/gcs_s2025/gcs_s2025/sitl_final_package/mavlink_integration
python3 telemetry_server.py
```
*Open your web browser on Windows and navigate to:* **`http://localhost:5000`**

### Step 4: Run the GCS Mission Swarm Controller
Open terminal tab 3:
```bash
su - immad_baber
cd /mnt/d/gcs_s2025/gcs_s2025/sitl_final_package/mavlink_integration
python3 main.py --drones 5
```

---

## 📊 4. Testing & Verification Results

* **Connection Status**: 3 separate `SITLAdapter` objects successfully connected to `udpin:0.0.0.0:14551-14553` concurrently.
* **Telemetry Server**: Emitted packets at 1 Hz from each drone to the frontend map layer via WebSocket.
* **Flight Trajectory**: Drones took off, flew in parallel formations, tracked color-coded Leaflet coordinates, landed on lower terrain, and disarmed cleanly with `0.0m` altitude displays.
