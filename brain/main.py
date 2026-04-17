import argparse

import uvicorn

from motor import MotorClient, ServoClient
from server import create_app
from vision import Vision


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam",   required=True, help="e.g. http://192.168.1.51:81/stream")
    ap.add_argument("--motor", required=True, help="e.g. http://192.168.1.50")
    ap.add_argument("--servo", default=None,  help="e.g. http://192.168.1.52 (optional)")
    ap.add_argument("--host",  default="0.0.0.0")
    ap.add_argument("--port",  type=int, default=8000)
    args = ap.parse_args()

    motors = MotorClient(args.motor)
    servos = ServoClient(args.servo) if args.servo else None
    vision = Vision(args.cam, motors)
    vision.start()

    app = create_app(vision, motors, servos)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
