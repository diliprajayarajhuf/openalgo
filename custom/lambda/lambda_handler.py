"""
AWS Lambda that starts and stops the OpenAlgo EC2 instance.

Invoked by two EventBridge schedules (infra/lambda.tf):
  {"action": "start"}  08:55 IST Mon-Fri, only if NSE trades today
  {"action": "stop"}   16:30 IST every day
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3

from nse_utils import is_market_open_today

INSTANCE_ID = os.environ["OPENALGO_INSTANCE_ID"]
IST = ZoneInfo("Asia/Kolkata")
ec2 = boto3.client("ec2")


def _state() -> str:
    reservations = ec2.describe_instances(InstanceIds=[INSTANCE_ID])["Reservations"]
    return reservations[0]["Instances"][0]["State"]["Name"]


def handler(event, context):
    action = (event or {}).get("action")
    state = _state()

    if action == "start":
        today = datetime.now(IST).date()
        if not is_market_open_today("XNSE", today):
            print("NSE is closed today, nothing to run")
            return {"status": "skipped", "reason": "market closed"}
        if state in ("running", "pending"):
            print(f"OpenAlgo instance already {state}")
        else:
            ec2.start_instances(InstanceIds=[INSTANCE_ID])
            print(f"Starting OpenAlgo instance {INSTANCE_ID} (was {state})")

    elif action == "stop":
        if state in ("stopped", "stopping"):
            print(f"OpenAlgo instance already {state}")
        else:
            ec2.stop_instances(InstanceIds=[INSTANCE_ID])
            print(f"Stopping OpenAlgo instance {INSTANCE_ID} (was {state})")

    else:
        raise ValueError(f"action must be 'start' or 'stop', got {action!r}")

    return {"status": 200}
