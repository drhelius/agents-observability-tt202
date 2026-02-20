#!/usr/bin/env python3
"""
Continuous Batch Runner for Fraud Detection Workflow

Runs batch_runner.py in a loop with a random delay (10-30 minutes)
between each execution. Runs forever until interrupted with Ctrl+C.

Usage:
    python continuous_runner.py
"""

import asyncio
import random
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from multi_transaction_simulator import run_batch_simulation


async def main():
    run_number = 0

    print("🔄 Continuous Batch Runner started. Press Ctrl+C to stop.\n")

    while True:
        run_number += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n{'#'*70}")
        print(f"  Run #{run_number} — {now}")
        print(f"{'#'*70}")

        try:
            await run_batch_simulation(
                num_transactions=15,
                delay_between=1.0,
                randomize_delay=True,
                shuffle_transactions=True,
            )
        except Exception as e:
            print(f"\n❌ Run #{run_number} failed: {e}")

        delay_minutes = random.randint(1, 6)
        next_run = datetime.now() + timedelta(minutes=delay_minutes)
        print(f"\n⏳ Next run in {delay_minutes} minutes (at {next_run.strftime('%H:%M:%S')})")
        await asyncio.sleep(delay_minutes * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n🛑 Continuous runner stopped.")
