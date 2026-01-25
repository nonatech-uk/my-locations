#!/bin/bash
# Daily FollowMee sync - run via cron at 5am

HC_URL="https://hc.mees.st/ping/32960f21-f84a-4635-9de5-94dfbca6e16c"

cd /home/stu/code/mylocation

# Signal start
curl -fsS -m 10 --retry 5 "${HC_URL}/start" > /dev/null 2>&1

# Run sync
if ./venv/bin/python3 gps/followmee_sync.py --daily >> /home/stu/code/mylocation/sync.log 2>&1; then
    # Success
    curl -fsS -m 10 --retry 5 "${HC_URL}" > /dev/null 2>&1
else
    # Failure
    curl -fsS -m 10 --retry 5 "${HC_URL}/fail" > /dev/null 2>&1
fi
