# Week 4 Report — Swarm Level Commands and Basic Formation

## Overview

Week 4 adds interactive **command-and-control** capabilities to the Ground Control Station (GCS). The system now supports:

- **Swarm commands**: arm all, takeoff all, land all — with concurrent execution
- **Individual drone control**: arm, takeoff, and land a single selected drone
- **Basic formation flight**: leader-follower triangle formation with 10m spacing
- **Formation logging**: inter-drone distances and positions logged to JSON-lines
- **REST API**: 12 new endpoints for all operations
- **GCS Dashboard**: interactive Swarm Command Panel with buttons, loading states, and feedback
- **Behavior test scenarios**: 3 automated test scripts exercising the full feature set

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                    GCS Web Dashboard (index.html)            │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │ Swarm Cmds   │ │ Individual   │ │ Formation Control    │ │
│  │ • Connect    │ │ • Arm One    │ │ • Triangle           │ │
│  │ • Arm All    │ │ • Takeoff    │ │ • Get Distances      │ │
│  │ • Takeoff All│ │ • Land One   │ │                      │ │
│  │ • Land All   │ │              │ │                      │ │
│  └──────┬───────┘ └──────┬───────┘ └──────────┬───────────┘ │
│         │                │                     │             │
│         └────────────────┼─────────────────────┘             │
│                          │ REST API (fetch)                  │
└──────────────────────────┼───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│               telemetry_server.py (Quart)                    │
│                                                              │
│  /api/swarm/connect       POST  Connect N drones             │
│  /api/swarm/arm_all       POST  Arm all drones               │
│  /api/swarm/takeoff_all   POST  Takeoff all                  │
│  /api/swarm/land_all      POST  Land all                     │
│  /api/drone/<id>/arm      POST  Arm one drone                │
│  /api/drone/<id>/takeoff  POST  Takeoff one drone            │
│  /api/drone/<id>/land     POST  Land one drone               │
│  /api/swarm/formation     POST  Move to formation            │
│  /api/swarm/status        GET   Swarm status                 │
│  /api/drone/<id>/status   GET   Single drone status          │
│  /api/swarm/formation/distances  GET  Inter-drone distances  │
│  /api/swarm/formation/log       GET  Formation log           │
│                                                              │
│  ┌────────────────┐  ┌────────────────┐                      │
│  │ SwarmManager   │  │FormationManager│                      │
│  │ (swarm_mgr)    │←─│ (formation_mgr)│                      │
│  └───────┬────────┘  └───────┬────────┘                      │
│          │                   │                               │
│          ▼                   ▼                               │
│  ┌────────────────────────────────────┐                      │
│  │     SITLAdapter (per drone)        │                      │
│  │  drone_1 ← udpin:0.0.0.0:14551    │                      │
│  │  drone_2 ← udpin:0.0.0.0:14552    │                      │
│  │  drone_3 ← udpin:0.0.0.0:14553    │                      │
│  └────────────────┬───────────────────┘                      │
│                   │ MAVLink                                  │
└───────────────────┼──────────────────────────────────────────┘
                    │
                    ▼
          ┌───────────────────┐
          │   SITL Instances  │
          │   (ArduCopter)    │
          │   via start_sitl  │
          └───────────────────┘
```

---

## Files Added

### 1. `swarm_manager.py` — Swarm Manager Module

**Purpose**: Central orchestration layer that holds references to all drone `SITLAdapter` instances and exposes swarm-wide + individual drone commands.

**Key class**: `SwarmManager`

| Method | Description |
|---|---|
| `add_drone(drone_id, connection_str)` | Connect and initialize one drone |
| `connect_swarm(num_drones)` | Connect N drones on consecutive UDP ports |
| `arm_all()` | Set GUIDED + arm every drone (concurrent threads) |
| `takeoff_all(altitude)` | Takeoff every drone (concurrent threads) |
| `land_all()` | Land every drone (concurrent threads) |
| `arm_drone(drone_id)` | Arm a single selected drone |
| `takeoff_drone(drone_id, altitude)` | Takeoff a single drone |
| `land_drone(drone_id)` | Land a single drone |
| `get_drone_status(drone_id)` | Return latest telemetry for one drone |
| `get_swarm_status()` | Return status for all drones |
| `get_connected_drone_ids()` | List of connected drone IDs |

**Thread safety**: All drone operations use `ThreadPoolExecutor` for concurrent execution and a threading lock for dict access.

---

### 2. `formation_manager.py` — Formation Logic

**Purpose**: Implements leader-follower and fixed-offset formation logic with GPS coordinate math.

**Formation: Triangle**
```
       drone_1 (LEADER)
      /              \
drone_2              drone_3
(-10m, -10m)       (+10m, -10m)
left/back           right/back
```

**Key class**: `FormationManager`

| Method | Description |
|---|---|
| `compute_formation_positions(type, spacing)` | Compute GPS positions for all drones in formation |
| `move_to_formation(type, spacing)` | Command each follower drone to its position |
| `log_formation_distances()` | Compute and log pairwise distances |

**GPS math**:
- Body-frame offsets (dx, dy in meters) are rotated by the leader's heading
- Meter offsets are converted to GPS degrees using `LAT_DEG_PER_METER` and `lon_deg_per_meter(lat)`
- Formation stays aligned with the leader's direction of flight

---

### 3. `formation_logger.py` — Formation State Logger

**Purpose**: Logs formation snapshots to `logs/formation_log.jsonl` for analysis.

Each entry contains:
```json
{
  "timestamp": "2026-06-30T09:30:00Z",
  "formation_type": "triangle",
  "target_positions": {"drone_1": {...}, "drone_2": {...}, "drone_3": {...}},
  "actual_positions": {"drone_1": {...}, "drone_2": {...}, "drone_3": {...}},
  "inter_drone_distances": {"drone_1<->drone_2": 14.14, ...},
  "extra": {"spacing": 10}
}
```

---

### 4. `test_swarm_scenarios.py` — Behavior-Based Test Scenarios

**Purpose**: Automated test script that exercises swarm commands via the REST API.

| Scenario | What it tests |
|---|---|
| **Scenario 1** | Connect 3 → Arm all → Takeoff all → Hover 15s → Land all |
| **Scenario 2** | Connect 3 → Arm drone_2 only → Takeoff drone_2 → Verify drone_1 NOT armed → Land drone_2 |
| **Scenario 3** | Connect 3 → Arm all → Takeoff all → Triangle formation → Log distances → Land all |

**Run options**:
```bash
python test_swarm_scenarios.py        # Run all 3 scenarios
python test_swarm_scenarios.py 1      # Run scenario 1 only
python test_swarm_scenarios.py 2      # Run scenario 2 only
python test_swarm_scenarios.py 3      # Run scenario 3 only
```

---

## Files Modified

### 5. `telemetry_server.py` — REST API Endpoints

**Changes**: Added 12 new REST API endpoints for swarm control, individual drone control, formation commands, and status queries.

```diff
+ from swarm_manager import SwarmManager
+ from formation_manager import FormationManager
+ import formation_logger
+
+ # Global SwarmManager and FormationManager instances
+ swarm_mgr = SwarmManager()
+ formation_mgr = FormationManager(swarm_mgr)
+
+ # ── Swarm Connection ──
+ @app.route("/api/swarm/connect", methods=["POST"])
+ @app.route("/api/swarm/arm_all", methods=["POST"])
+ @app.route("/api/swarm/takeoff_all", methods=["POST"])
+ @app.route("/api/swarm/land_all", methods=["POST"])
+
+ # ── Individual Drone Commands ──
+ @app.route("/api/drone/<drone_id>/arm", methods=["POST"])
+ @app.route("/api/drone/<drone_id>/takeoff", methods=["POST"])
+ @app.route("/api/drone/<drone_id>/land", methods=["POST"])
+
+ # ── Status ──
+ @app.route("/api/swarm/status", methods=["GET"])
+ @app.route("/api/drone/<drone_id>/status", methods=["GET"])
+
+ # ── Formation ──
+ @app.route("/api/swarm/formation", methods=["POST"])
+ @app.route("/api/swarm/formation/distances", methods=["GET"])
+ @app.route("/api/swarm/formation/log", methods=["GET"])
```

All command endpoints use `loop.run_in_executor()` to run blocking MAVLink operations in background threads, keeping the Quart server responsive.

**Recent Architecture Update**: Added a standalone background worker (`telemetry_polling_worker`) inside `telemetry_server.py` that continuously polls all connected drones for telemetry (Altitude, Battery, Mode, Position) and broadcasts it over WebSockets. This fix fully decouples manual UI control from the autonomous `main.py` script, preventing command conflicts where `main.py` would instantly override manual UI commands.

---

### 6. `index.html` — GCS Dashboard Command Panel

**Changes**: Added three new interactive sections to the sidebar:

#### Swarm Commands Section
- 🔗 **CONNECT** — Connect 3 SITL drones
- 🔓 **ARM ALL** — Arm all connected drones
- 🚀 **TAKEOFF** — Takeoff all drones (with altitude input)
- 🛬 **LAND ALL** — Land all drones
- Altitude input field (default 10m)

#### Formation Section
- 🔺 **TRIANGLE** — Move to triangle formation
- 📏 **DISTANCES** — Fetch and display inter-drone distances
- Distance grid showing pairwise distances

#### Individual Drone Control Section
- Shows "SELECTED: DRONE_X" label
- **ARM** / **TAKEOFF** / **LAND** buttons for the selected drone

**UI Features**:
- Loading spinner animation during API calls
- Green success / red error feedback on buttons
- All command results logged to the GCS console
- Formation distances displayed in a grid

---

## File Summary

| File | Status | Purpose |
|---|---|---|
| `swarm_manager.py` | **NEW** | Swarm orchestration (arm/takeoff/land all + individual) |
| `formation_manager.py` | **NEW** | Formation logic (triangle leader-follower) |
| `formation_logger.py` | **NEW** | Formation state logging to JSONL |
| `test_swarm_scenarios.py` | **NEW** | 3 behavior-based test scenarios |
| `telemetry_server.py` | **MODIFIED** | 12 new REST API endpoints |
| `index.html` | **MODIFIED** | Swarm command panel in dashboard |

---

## How to Run — Exact Commands

### Step 1: Start SITL Drones (in WSL)

```bash
# Open a WSL terminal
cd /mnt/d/gcs_s2025/gcs_s2025/sitl_final_package

# Start 3 ArduCopter SITL instances
bash start_sitl.sh 3

# Wait ~3-4 minutes for GPS lock
# Monitor with: tail -f /tmp/sitl_instance_0.log
```

### Step 2: Start the GCS Server (in WSL — same or new terminal)

```bash
cd /mnt/d/gcs_s2025/gcs_s2025/sitl_final_package/mavlink_integration

# Activate your Python virtual environment (if using one)
source ../venv/bin/activate  # or ../final_venv/bin/activate

# Start the telemetry server
python telemetry_server.py
```

The server will start on `http://0.0.0.0:5000`.

### Step 3: Open the GCS Dashboard (in your browser)

```
http://localhost:5000
```

*(Note: You do **not** need to run `main.py` if you simply want to manually control the drones via the dashboard. The server now features its own background telemetry poller that operates completely standalone).*

### Step 4: Use the Dashboard

1. Click **CONNECT** → Connects to 3 SITL drones
2. Click **ARM ALL** → Arms all drones (sets GUIDED mode automatically)
3. Set altitude to **10** in the input field
4. Click **TAKEOFF** → All drones take off to 10m
5. Click **TRIANGLE** → Drones move into triangle formation
6. Click **DISTANCES** → Shows inter-drone distances
7. Click on a drone tab (e.g., **DRONE 2**) → Individual commands appear
8. Click **LAND ALL** → All drones land

### Step 5: Run Automated Tests (optional, in another WSL terminal)

```bash
cd /mnt/d/gcs_s2025/gcs_s2025/sitl_final_package/mavlink_integration

# Run all 3 test scenarios
python test_swarm_scenarios.py

# Or run a specific scenario
python test_swarm_scenarios.py 1   # Swarm lifecycle
python test_swarm_scenarios.py 2   # Individual drone control
python test_swarm_scenarios.py 3   # Formation flight
```

---

## Log Files

| File | Location | Contents |
|---|---|---|
| `drone_X_telemetry.log` | `logs/` | Per-drone telemetry JSON-lines |
| `formation_log.jsonl` | `logs/` | Formation snapshots with distances |
| `swarm_telemetry_combined.log` | `logs/` | Combined swarm telemetry |
| Server log | `logs/*.txt` | Timestamped server log with all operations |

---

## Weekly Deliverable Checklist

| Requirement | Status | Implementation |
|---|---|---|
| ✅ Arm all drones | Done | `POST /api/swarm/arm_all` + ARM ALL button |
| ✅ Take off all drones | Done | `POST /api/swarm/takeoff_all` + TAKEOFF button |
| ✅ Land all drones | Done | `POST /api/swarm/land_all` + LAND ALL button |
| ✅ Send command to one selected drone | Done | `POST /api/drone/<id>/arm|takeoff|land` + Individual panel |
| ✅ Move swarm in basic formation | Done | `POST /api/swarm/formation` + TRIANGLE button |
| ✅ Formation: drone_1 = leader | Done | `FormationManager.LEADER_ID = "drone_1"` |
| ✅ Formation: drone_2 = 10m left/back | Done | Offset `(-10, -10)` meters |
| ✅ Formation: drone_3 = 10m right/back | Done | Offset `(+10, -10)` meters |
| ✅ Behavior-based test scenarios | Done | `test_swarm_scenarios.py` (3 scenarios) |
| ✅ Test on 2-3 drones | Done | Default connects 3 drones |
| ✅ Visualize formation distances | Done | Dashboard distance grid + console logs |
| ✅ Log formation data | Done | `formation_log.jsonl` via `formation_logger.py` |

---

*Report generated on 2026-06-30.*

---

## Bug Fixes & Improvements — 2026-07-01

The following bugs were identified during live testing of the Week 4 GCS dashboard and corrected. All fixes preserve existing functionality.

---

### Bug 1 — Altitude Display Always Shows 10m (Frontend + Backend)

**Files changed**: `drone_controller.py`, `index.html`

#### Root Cause

`drone_controller.py` `takeoff()` used a flat `time.sleep(10)` and returned `True` unconditionally:

```python
# BEFORE (broken):
master.mav.command_long_send(...)
time.sleep(10)   # only waits 10 seconds regardless of altitude
return True      # always reports success even if drone hasn't climbed yet
```

In 10 seconds, an ArduCopter SITL drone climbs approximately **10m** regardless of the requested altitude. So when the user set altitude to 13m or 15m, the backend declared "TAKEOFF — Success" after 10 seconds, but the drone was still climbing. The FLIGHT TELEMETRY panel correctly reported the **real drone altitude** from `GLOBAL_POSITION_INT.relative_alt`, which at that moment was still ~10m.

#### Fix Applied — `drone_controller.py`

Replaced the flat sleep with a **polling loop** that monitors `GLOBAL_POSITION_INT` every 0.5 seconds and waits until the drone reaches **90% of the commanded altitude** (max 60-second timeout):

```python
# AFTER (fixed):
target_threshold = altitude * 0.90
deadline = time.time() + 60
while time.time() < deadline:
    master.recv_match(blocking=False)
    pos = master.messages.get('GLOBAL_POSITION_INT')
    if pos:
        current_alt = pos.relative_alt / 1000.0
        if current_alt >= target_threshold:
            return True   # confirmed reached altitude
    time.sleep(0.5)
```

> **Key insight**: The telemetry was always accurate — the drone WAS at 10m. The bug was that the backend lied about reaching the target altitude after only 10 seconds.

#### Fix Applied — `index.html`

Enhanced the ALTITUDE card in FLIGHT TELEMETRY to show both **actual** and **commanded** altitude:

- **Large number** = live actual altitude from MAVLink telemetry
- **`/ 15 m target`** = the altitude you requested via the TAKEOFF button
- **Progress bar** = fill shows percentage of target reached
- **Status badge**: `↑ CLIMBING` (yellow) while ascending → `✅ AT TARGET` (green) when within 5% of target

A new JavaScript variable `commandedAltitude` is set each time `cmdTakeoffAll()` or `cmdTakeoffOne()` is called, so the target is always in sync with the last takeoff command.

---

### Bug 2 — Individual LAND Button Did Not Work

**Files changed**: `drone_controller.py`, `sitl_adapter.py`

#### Root Cause A — Single-shot land command with no confirmation

`drone_controller.py` `land_drone()` sent `MAV_CMD_NAV_LAND` exactly once and returned immediately:

```python
# BEFORE (broken):
master.mav.command_long_send(...)  # sent once, no retry
return True                        # always says success
```

If the MAVLink link was busy, the packet was dropped and the drone simply never got the command.

#### Fix Applied — `drone_controller.py`

Replaced with a **3-attempt retry loop** that checks the HEARTBEAT after each attempt to confirm that the drone's mode switched to `LAND`:

```python
# AFTER (fixed):
for attempt in range(3):
    master.mav.command_long_send(...)
    time.sleep(1)
    master.recv_match(blocking=False)
    hb = master.messages.get('HEARTBEAT')
    if hb:
        mode_str = mavutil.mode_string_v10(hb)
        if 'LAND' in mode_str.upper():
            return True   # confirmed LAND mode
    time.sleep(1)
```

#### Root Cause B — `sitl_adapter.py` land() blocked forever

`sitl_adapter.py` `land()` had a `while True` loop waiting for `armed=False AND alt < 0.3`. If the landing command was never accepted (e.g. mode didn't switch), this loop ran **indefinitely**, permanently blocking that drone's thread. All future commands to that drone would also hang.

```python
# BEFORE (broken):
while True:           # ← no exit condition if landing fails
    ...
    if not armed and alt < 0.3:
        break
```

#### Fix Applied — `sitl_adapter.py`

Added a **120-second deadline** so the loop exits gracefully even if landing fails, with a warning logged:

```python
# AFTER (fixed):
deadline = time.time() + 120   # max 2 minutes
while time.time() < deadline:
    ...
    if not armed and alt < 0.3:
        logging.info("✅ Drone has landed and disarmed successfully!")
        return

logging.warning("⚠️ Land timeout (120s) — drone may not have fully landed")
```

---

### Bug 3 — Individual Takeoff Altitude Shared with Fleet Altitude Input

**Files changed**: `index.html`

#### Root Cause

The **Individual Drone Control** section had no altitude input of its own. `cmdTakeoffOne()` read from `#alt-input` which belongs to the **FLEET CONTROL** section at the top of the sidebar — a different visual section that users didn't associate with individual drone control.

#### Fix Applied — `index.html`

Added a **dedicated altitude input field `#alt-input-one`** directly inside the Individual Drone Control section, so users see and set altitude in the same visual context as the ARM / TAKEOFF / LAND buttons for individual drones.

Updated `cmdTakeoffOne()` to read from `#alt-input-one`:
```js
// BEFORE:
const alt = parseFloat(document.getElementById('alt-input').value) || 10;

// AFTER:
const alt = parseFloat(document.getElementById('alt-input-one').value) || 10;
```

---

### What ARM Does — Clarification

This was a frequent question during testing. The full drone command lifecycle is:

| Step | Command | Effect |
|---|---|---|
| 1 | **CONNECT** | Opens MAVLink UDP connection to SITL instance. Motors are off, drone is powered but inert. |
| 2 | **ARM** | Waits for GPS+EKF lock → sets mode to GUIDED → sends `MAV_CMD_COMPONENT_ARM_DISARM` → **enables motors**. Without arming, TAKEOFF is rejected. |
| 3 | **TAKEOFF** | Sends `MAV_CMD_NAV_TAKEOFF` with target altitude → motors spin up → drone ascends. Now waits for actual altitude to be reached (fixed). |
| 4 | **LAND** | Sends `MAV_CMD_NAV_LAND` with retry → drone descends → auto-disarms on touchdown. |

> **Safety design**: Arming is a mandatory gate that prevents accidental motor spin-up. A drone will refuse to arm if GPS fix < 3D, battery is critical, or any pre-arm check fails.

---

### Bug 4 — Individual Arm and Land Buttons Hanging the UI

**Files changed**: `drone_controller.py`, `sitl_adapter.py`, `swarm_manager.py`

#### Root Cause
When the UI sent an "arm" or "land" command, the REST API invoked backend functions that **blocked until completion**:
1. `arm_drone` contained a `while True` loop that waited indefinitely for a GPS lock and for the arming command to be accepted. If GPS failed, the thread hung forever.
2. `sitl_adapter.land()` contained a loop that waited until the drone reached an altitude of `<0.3m`. This meant the `POST /api/drone/<id>/land` request would not return until the drone physically touched the ground (up to 2 minutes), keeping the UI button in a perpetual "loading" state.

#### Fix Applied

1. **Timeouts in `arm_drone`**: Added a strict 30-second timeout for acquiring a GPS lock, and a 15-second timeout for the arming command to be accepted. If it fails, it now aborts and returns an error immediately.
2. **Non-blocking `land`**: Added a `wait_for_land=False` parameter to `sitl_adapter.land()`. The REST API via `swarm_manager.py` now passes `False`, so the land command is dispatched to the drone asynchronously. The API returns success immediately, and the drone continues to descend in the background, keeping the UI responsive.

---

### Bug 5 — Individual "LAND" Command Causes Drone to Fly Away

**Files changed**: `drone_controller.py`

#### Root Cause
When commanding a single drone to land, `land_drone()` was sending `MAV_CMD_NAV_LAND` with the latitude and longitude parameters (`param5` and `param6`) set to exactly `0, 0`. ArduCopter SITL interprets `0, 0` as a command to fly to **Null Island** (the equator off the coast of Africa) and land there. Because the drone was trying to fly thousands of miles horizontally, it appeared to ignore the landing altitude command entirely, and its telemetry in the UI stayed at `10.0m` altitude.

#### Fix Applied
Changed the landing mechanism in `land_drone()` from `MAV_CMD_NAV_LAND` to a **mode change to LAND**:
```python
master.mav.set_mode_send(
    master.target_system,
    mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
    mode_id
)
```
Setting the flight mode to `LAND` guarantees that the drone drops straight down from its *exact current position* without trying to navigate to a target coordinate.

---

### Bug 6 — Server Crash (Disconnected) during Individual Commands

**Files changed**: `drone_controller.py`

#### Root Cause
When the UI invoked individual `ARM` or `LAND` commands, the server occasionally crashed, and the UI displayed `[SYSTEM] ⚠ Disconnected. Retrying in 3s...`.
This was caused by a **race condition over the MAVLink socket**:
- The `telemetry_polling_worker` runs continuously in the background, reading all messages from the socket (via `recv_match(blocking=False)`) to keep `master.messages` up to date.
- The `arm_drone` and `land_drone` loops were *also* calling `recv_match()`, attempting to "steal" messages directly from the socket to check for a `HEARTBEAT`.
- Because the polling worker was so fast, the `arm` or `land` loops would often time out or encounter a null object reference, throwing a fatal Exception and crashing the background thread handling the API request.

#### Fix Applied
Removed all `recv_match()` calls from `arm_drone` and `land_drone`. Instead, these functions now sleep briefly and read the safely cached state directly:
- **Arming**: Checks `master.motors_armed()` which reads the background worker's cached heartbeat.
- **Landing**: Checks `master.messages.get('HEARTBEAT')` to verify the `LAND` mode transition.

This completely decouples command dispatch from telemetry ingestion, preventing the threads from colliding.

---

### Bug 7 — Drones Not Moving During Formation Commands

**Files changed**: `sitl_adapter.py`, `drone_controller.py`

#### Root Cause
When the "TRIANGLE" formation button was clicked, the backend attempted to read the leader drone's current position to calculate the follower offsets. However, `get_position()` and `wait_until_position_reached()` were both using `master.recv_match(blocking=False)` to fetch the `GLOBAL_POSITION_INT` directly from the socket. 
Because the background telemetry worker was constantly draining the socket, these functions almost always returned `None`. This caused the formation calculation to abort silently, meaning no movement commands were ever sent to the followers, and the API request hung indefinitely.

#### Fix Applied
Changed `get_position()` and `wait_until_position_reached()` to read directly from the safely cached `master.messages.get('GLOBAL_POSITION_INT')` dictionary. This ensures they always get the latest position immediately without fighting the telemetry worker for socket data, allowing the formation offsets to compute instantly and the drones to start moving.

---

### Final Updated File Summary

| File | Change Type | Summary |
|---|---|---|\
| `drone_controller.py` | **BUGFIX** | `takeoff()` waits for actual altitude. `land_drone()` sets mode to `LAND`. `arm_drone()` has 30s/15s timeouts. Eliminated `recv_match` race conditions in all movement functions. |
| `sitl_adapter.py` | **BUGFIX** | `land()` loop has a 120s timeout and a `wait_for_land=False` option. `get_position()` now safely reads from the telemetry cache. |
| `swarm_manager.py` | **BUGFIX** | `land_all` and `land_drone` use `wait_for_land=False` so API requests don't hang the server. |
| `index.html` | **IMPROVEMENT** | Altitude card shows actual vs commanded altitude with progress bar. Individual drone control now has its own altitude input. |

---

*Bug fixes documented on 2026-07-01.*
