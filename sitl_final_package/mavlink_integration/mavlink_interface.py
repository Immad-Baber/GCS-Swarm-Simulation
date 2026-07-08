# mavlink_interface.py
from pymavlink import mavutil

class MAVLinkInterface:
    def __init__(self, connection_str: str):
        self.connection_str = connection_str
        self.master = None

    def connect(self):
        print(f"[INFO] Connecting to {self.connection_str}...")
        self.master = mavutil.mavlink_connection(self.connection_str)
        try:
            self.wait_heartbeat()
        except Exception:
            self.close()
            raise

    def wait_heartbeat(self, timeout=30):
        print("[INFO] Waiting for heartbeat...")
        heartbeat = self.master.wait_heartbeat(timeout=timeout)
        if heartbeat is None:
            raise TimeoutError(f"No heartbeat from {self.connection_str} within {timeout}s")
        print(f"[INFO] Heartbeat received from system {self.master.target_system}, component {self.master.target_component}")

    def send_command_long(self, command, params):
        print(f"[DEBUG] Sending command {command} with params {params}")
        self.master.mav.command_long_send(
            self.master.target_system,
            self.master.target_component,
            command,
            0,  # confirmation
            *params
        )

    def recv_msg(self, msg_type="COMMAND_ACK", blocking=True):
        msg = self.master.recv_match(type=msg_type, blocking=blocking)
        if msg:
            print(f"[RECV] {msg}")
        return msg

    def get_master(self):
        return self.master

    def close(self):
        if self.master is not None:
            self.master.close()
            self.master = None
