import requests


class MotorClient:
    def __init__(self, base_url):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()

    def is_connected(self):
        """Check if motor board is reachable."""
        try:
            r = self.session.get(f"{self.base}/", timeout=0.5)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def drive(self, left, right):
        try:
            self.session.get(
                f"{self.base}/drive",
                params={"l": int(left), "r": int(right)},
                timeout=0.25,
            )
        except requests.RequestException:
            pass

    def stop(self):
        try:
            self.session.get(f"{self.base}/stop", timeout=0.25)
        except requests.RequestException:
            pass

    def rssi(self):
        try:
            r = self.session.get(f"{self.base}/rssi", timeout=0.25)
            return int(r.text.strip())
        except (requests.RequestException, ValueError):
            return None

    def distance(self):
        """Get ultrasonic distance in cm. Returns None if sensor not available."""
        try:
            r = self.session.get(f"{self.base}/distance", timeout=0.25)
            v = float(r.text.strip())
            return v if v >= 0 else None
        except (requests.RequestException, ValueError):
            return None


class ServoClient:
    def __init__(self, base_url):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()

    def move(self, pan, tilt):
        try:
            self.session.get(
                f"{self.base}/servo",
                params={"pan": int(pan), "tilt": int(tilt)},
                timeout=0.25,
            )
        except requests.RequestException:
            pass

    def center(self):
        try:
            self.session.get(f"{self.base}/center", timeout=0.25)
        except requests.RequestException:
            pass

    def status(self):
        try:
            r = self.session.get(f"{self.base}/servo_status", timeout=0.25)
            return r.json()
        except (requests.RequestException, ValueError):
            return {"pan": 90, "tilt": 90}
