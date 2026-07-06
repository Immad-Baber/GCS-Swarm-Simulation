# swarm_manager.py
# ─────────────────────────────────────────────────────────────────────────────
# Week 4 – Swarm Manager
# Central orchestration layer that holds references to every connected
# SITLAdapter and exposes swarm-wide and individual drone commands.
# ─────────────────────────────────────────────────────────────────────────────

import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from sitl_adapter import SITLAdapter


class SwarmManager:
    """
    Manages a fleet of drones.

    Usage:
        sm = SwarmManager()
        sm.add_drone("drone_1", "udpin:0.0.0.0:14551")
        sm.add_drone("drone_2", "udpin:0.0.0.0:14552")
        sm.add_drone("drone_3", "udpin:0.0.0.0:14553")
        sm.arm_all()
        sm.takeoff_all(10)
        sm.land_all()
    """

    def __init__(self):
        # {drone_id: SITLAdapter}
        self.drones = {}
        # Lock for thread-safe access to the drones dict
        self._lock = threading.Lock()
        logging.info("[SwarmManager] Initialized (empty fleet)")

    # ── Connection ────────────────────────────────────────────────────────

    def add_drone(self, drone_id: str, connection_str: str) -> bool:
        """
        Connect and initialize a single drone.
        Returns True on success, False on failure.
        """
        try:
            logging.info(f"[SwarmManager] Connecting {drone_id} via {connection_str} ...")
            adapter = SITLAdapter(drone_id, connection_str)
            adapter.initialize()
            with self._lock:
                self.drones[drone_id] = adapter
            logging.info(f"[SwarmManager] ✅ {drone_id} connected and initialized")
            return True
        except Exception as e:
            logging.error(f"[SwarmManager] ❌ Failed to add {drone_id}: {e}")
            return False

    def connect_swarm(self, num_drones: int = 3) -> dict:
        """
        Connect to *num_drones* SITL instances on consecutive UDP ports
        starting at 14551.  Returns a summary dict.
        """
        results = {}
        # Connect drones concurrently with a thread pool
        with ThreadPoolExecutor(max_workers=num_drones) as pool:
            futures = {}
            for i in range(num_drones):
                drone_id = f"drone_{i + 1}"
                port = 14551 + i
                connection_str = f"udp:127.0.0.1:{port}"
                futures[pool.submit(self.add_drone, drone_id, connection_str)] = drone_id

            for future in as_completed(futures):
                drone_id = futures[future]
                try:
                    results[drone_id] = future.result()
                except Exception as e:
                    logging.error(f"[SwarmManager] ❌ {drone_id} connection thread failed: {e}")
                    results[drone_id] = False

        logging.info(f"[SwarmManager] connect_swarm results: {results}")
        return results

    # ── Swarm-wide commands ───────────────────────────────────────────────

    def _run_on_all(self, fn_name: str, *args, **kwargs) -> dict:
        """
        Execute a method on every adapter concurrently.
        *fn_name* is a string attribute name on SITLAdapter.
        Returns {drone_id: True/False}.
        """
        results = {}
        with self._lock:
            drone_items = list(self.drones.items())

        def _run(drone_id, adapter):
            try:
                fn = getattr(adapter, fn_name)
                return fn(*args, **kwargs)
            except Exception as e:
                logging.error(f"[SwarmManager] {fn_name} failed for {drone_id}: {e}")
                return False

        with ThreadPoolExecutor(max_workers=len(drone_items) or 1) as pool:
            futures = {
                pool.submit(_run, did, adp): did for did, adp in drone_items
            }
            for future in as_completed(futures):
                did = futures[future]
                try:
                    results[did] = future.result()
                except Exception as e:
                    results[did] = False
                    logging.error(f"[SwarmManager] {fn_name} thread error for {did}: {e}")

        logging.info(f"[SwarmManager] {fn_name} → {results}")
        return results

    def arm_all(self) -> dict:
        """
        Set GUIDED mode and arm every connected drone concurrently.
        Returns {drone_id: True/False}.
        """
        results = {}
        with self._lock:
            drone_items = list(self.drones.items())

        def _arm_one(drone_id, adapter):
            try:
                if not adapter.set_mode("GUIDED"):
                    logging.error(f"[SwarmManager] {drone_id} failed to set GUIDED mode")
                    return False
                if not adapter.arm_vehicle():
                    logging.error(f"[SwarmManager] {drone_id} failed to arm")
                    return False
                adapter.log_status()
                logging.info(f"[SwarmManager] ✅ {drone_id} armed")
                return True
            except Exception as e:
                logging.error(f"[SwarmManager] arm failed for {drone_id}: {e}")
                return False

        with ThreadPoolExecutor(max_workers=len(drone_items) or 1) as pool:
            futures = {
                pool.submit(_arm_one, did, adp): did for did, adp in drone_items
            }
            for future in as_completed(futures):
                did = futures[future]
                try:
                    results[did] = future.result()
                except Exception as e:
                    results[did] = False

        logging.info(f"[SwarmManager] arm_all → {results}")
        return results

    def takeoff_all(self, altitude: float = 10.0) -> dict:
        """Takeoff every connected drone to *altitude* meters and start mission."""
        results = {}
        with self._lock:
            drone_items = list(self.drones.items())

        import threading
        import os
        import math
        from waypoint_navigator import WaypointNavigator

        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
        WAYPOINT_FILE = os.path.join(SCRIPT_DIR, "waypoints.json")

        temp_navigator = WaypointNavigator(None)
        try:
            base_waypoints = temp_navigator.load_from_json(WAYPOINT_FILE)
        except Exception as e:
            logging.error(f"❌ Failed to load waypoints: {e}")
            base_waypoints = []

        OFFSETS = {
            0: (0,    0),
            1: (-25, -10),
            2: (25,  -10),
            3: (-50, -20),
            4: (50,  -20),
            5: (0,   -20),
            6: (-75, -30),
            7: (75,  -30),
            8: (-25, -30),
            9: (25,  -30),
        }

        def _mission_worker(drone_id, adapter, waypoints):
            logging.info(f"[{drone_id}] Starting waypoint navigation...")
            navigator = WaypointNavigator(adapter)
            if not navigator.execute(waypoints):
                logging.error(f"[{drone_id}] ❌ Waypoint navigation failed")
            else:
                logging.info(f"[{drone_id}] ✅ MISSION COMPLETE")

        def _takeoff_one(drone_id, adapter):
            try:
                ok = adapter.takeoff(altitude)
                adapter.log_status()
                logging.info(f"[SwarmManager] {'✅' if ok else '❌'} {drone_id} takeoff({'ok' if ok else 'fail'})")
                
                if ok and base_waypoints:
                    # Calculate drone-specific waypoints
                    try:
                        drone_idx = int(drone_id.split('_')[1]) - 1
                    except:
                        drone_idx = 0

                    lat_deg_per_meter = 1.0 / 111320.0
                    base_lat = base_waypoints[0]["latitude"]
                    lon_deg_per_meter = 1.0 / (111320.0 * math.cos(math.radians(base_lat)))

                    lat1, lon1 = 33.6844, 73.0479
                    lat2 = base_waypoints[0]["latitude"]
                    lon2 = base_waypoints[0]["longitude"]
                    dy_path = lat2 - lat1
                    dx_path = (lon2 - lon1) * math.cos(math.radians(lat1))
                    bearing = math.atan2(dx_path, dy_path)

                    dx_body, dy_body = OFFSETS.get(drone_idx, (0, 0))
                    dx = dx_body * math.cos(bearing) + dy_body * math.sin(bearing)
                    dy = -dx_body * math.sin(bearing) + dy_body * math.cos(bearing)

                    offset_lat = dy * lat_deg_per_meter
                    offset_lon = dx * lon_deg_per_meter

                    drone_waypoints = []
                    for wp in base_waypoints:
                        drone_waypoints.append({
                            "latitude":  wp["latitude"]  + offset_lat,
                            "longitude": wp["longitude"] + offset_lon,
                            "altitude":  wp["altitude"]
                        })

                    # Start mission in a background thread so takeoff_all can return
                    threading.Thread(target=_mission_worker, args=(drone_id, adapter, drone_waypoints), daemon=True).start()

                return ok
            except Exception as e:
                logging.error(f"[SwarmManager] takeoff failed for {drone_id}: {e}")
                return False

        with ThreadPoolExecutor(max_workers=len(drone_items) or 1) as pool:
            futures = {
                pool.submit(_takeoff_one, did, adp): did for did, adp in drone_items
            }
            for future in as_completed(futures):
                did = futures[future]
                try:
                    results[did] = future.result()
                except Exception as e:
                    results[did] = False

        logging.info(f"[SwarmManager] takeoff_all({altitude}m) → {results}")
        return results

    def land_all(self) -> dict:
        """Land every connected drone."""
        results = {}
        with self._lock:
            drone_items = list(self.drones.items())

        def _land_one(drone_id, adapter):
            try:
                adapter.land(wait_for_land=False)
                logging.info(f"[SwarmManager] ✅ {drone_id} land command sent")
                return True
            except Exception as e:
                logging.error(f"[SwarmManager] land failed for {drone_id}: {e}")
                return False

        with ThreadPoolExecutor(max_workers=len(drone_items) or 1) as pool:
            futures = {
                pool.submit(_land_one, did, adp): did for did, adp in drone_items
            }
            for future in as_completed(futures):
                did = futures[future]
                try:
                    results[did] = future.result()
                except Exception as e:
                    results[did] = False

        logging.info(f"[SwarmManager] land_all → {results}")
        return results

    # ── Individual drone commands ─────────────────────────────────────────

    def get_adapter(self, drone_id: str) -> SITLAdapter:
        """Return the SITLAdapter for *drone_id*, or None."""
        with self._lock:
            return self.drones.get(drone_id)

    def arm_drone(self, drone_id: str) -> bool:
        """Arm a single drone by ID."""
        adapter = self.get_adapter(drone_id)
        if adapter is None:
            logging.error(f"[SwarmManager] arm_drone: {drone_id} not found")
            return False
        try:
            if not adapter.set_mode("GUIDED"):
                return False
            if not adapter.arm_vehicle():
                return False
            adapter.log_status()
            logging.info(f"[SwarmManager] ✅ {drone_id} armed (individual)")
            return True
        except Exception as e:
            logging.error(f"[SwarmManager] arm_drone {drone_id} error: {e}")
            return False

    def takeoff_drone(self, drone_id: str, altitude: float = 10.0) -> bool:
        """Takeoff a single drone by ID and start mission."""
        adapter = self.get_adapter(drone_id)
        if adapter is None:
            logging.error(f"[SwarmManager] takeoff_drone: {drone_id} not found")
            return False

        import threading
        import os
        import math
        from waypoint_navigator import WaypointNavigator

        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
        WAYPOINT_FILE = os.path.join(SCRIPT_DIR, "waypoints.json")

        temp_navigator = WaypointNavigator(None)
        try:
            base_waypoints = temp_navigator.load_from_json(WAYPOINT_FILE)
        except Exception as e:
            logging.error(f"❌ Failed to load waypoints: {e}")
            base_waypoints = []

        OFFSETS = {
            0: (0,    0),
            1: (-25, -10),
            2: (25,  -10),
            3: (-50, -20),
            4: (50,  -20),
            5: (0,   -20),
            6: (-75, -30),
            7: (75,  -30),
            8: (-25, -30),
            9: (25,  -30),
        }

        def _mission_worker(d_id, adp, waypoints):
            logging.info(f"[{d_id}] Starting waypoint navigation...")
            navigator = WaypointNavigator(adp)
            if not navigator.execute(waypoints):
                logging.error(f"[{d_id}] ❌ Waypoint navigation failed")
            else:
                logging.info(f"[{d_id}] ✅ MISSION COMPLETE")

        try:
            ok = adapter.takeoff(altitude)
            adapter.log_status()
            logging.info(f"[SwarmManager] {'✅' if ok else '❌'} {drone_id} takeoff({altitude}m) individual")
            
            if ok and base_waypoints:
                try:
                    drone_idx = int(drone_id.split('_')[1]) - 1
                except:
                    drone_idx = 0

                lat_deg_per_meter = 1.0 / 111320.0
                base_lat = base_waypoints[0]["latitude"]
                lon_deg_per_meter = 1.0 / (111320.0 * math.cos(math.radians(base_lat)))

                lat1, lon1 = 33.6844, 73.0479
                lat2 = base_waypoints[0]["latitude"]
                lon2 = base_waypoints[0]["longitude"]
                dy_path = lat2 - lat1
                dx_path = (lon2 - lon1) * math.cos(math.radians(lat1))
                bearing = math.atan2(dx_path, dy_path)

                dx_body, dy_body = OFFSETS.get(drone_idx, (0, 0))
                dx = dx_body * math.cos(bearing) + dy_body * math.sin(bearing)
                dy = -dx_body * math.sin(bearing) + dy_body * math.cos(bearing)

                offset_lat = dy * lat_deg_per_meter
                offset_lon = dx * lon_deg_per_meter

                drone_waypoints = []
                for wp in base_waypoints:
                    drone_waypoints.append({
                        "latitude":  wp["latitude"]  + offset_lat,
                        "longitude": wp["longitude"] + offset_lon,
                        "altitude":  wp["altitude"]
                    })

                threading.Thread(target=_mission_worker, args=(drone_id, adapter, drone_waypoints), daemon=True).start()

            return ok
        except Exception as e:
            logging.error(f"[SwarmManager] takeoff_drone {drone_id} error: {e}")
            return False

    def land_drone(self, drone_id: str) -> bool:
        """Land a single drone by ID."""
        adapter = self.get_adapter(drone_id)
        if adapter is None:
            logging.error(f"[SwarmManager] land_drone: {drone_id} not found")
            return False
        try:
            adapter.land(wait_for_land=False)
            logging.info(f"[SwarmManager] ✅ {drone_id} land command sent (individual)")
            return True
        except Exception as e:
            logging.error(f"[SwarmManager] land_drone {drone_id} error: {e}")
            return False

    # ── Status ────────────────────────────────────────────────────────────

    def get_drone_status(self, drone_id: str) -> dict:
        """
        Return the latest cached telemetry for a single drone.
        Returns a dict with position, battery, mode, armed status.
        """
        adapter = self.get_adapter(drone_id)
        if adapter is None:
            return {"error": f"{drone_id} not found"}

        status = {"drone_id": drone_id}
        try:
            # Drain pending messages to refresh cache
            while True:
                m = adapter.master.recv_match(blocking=False)
                if m is None:
                    break

            # Position
            pos = adapter.master.messages.get('GLOBAL_POSITION_INT')
            if pos:
                status["position"] = {
                    "lat": pos.lat / 1e7,
                    "lon": pos.lon / 1e7,
                    "alt": max(0.0, pos.relative_alt / 1000.0),
                }

            # Battery
            sys_status = adapter.master.messages.get('SYS_STATUS')
            if sys_status:
                status["battery"] = {
                    "voltage": sys_status.voltage_battery / 1000.0,
                    "remaining": sys_status.battery_remaining,
                    "current": sys_status.current_battery / 100.0,
                }

            # Mode & armed
            from pymavlink import mavutil
            hb = adapter.master.messages.get('HEARTBEAT')
            if hb:
                status["mode"] = mavutil.mode_string_v10(hb)
                status["armed"] = bool(
                    hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
                )
        except Exception as e:
            status["error"] = str(e)

        return status

    def get_swarm_status(self) -> dict:
        """Return status for every connected drone."""
        with self._lock:
            drone_ids = list(self.drones.keys())
        return {did: self.get_drone_status(did) for did in drone_ids}

    def get_connected_drone_ids(self) -> list:
        """Return a list of all connected drone IDs."""
        with self._lock:
            return list(self.drones.keys())
