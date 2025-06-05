#!/bin/bash
SLEEP_SEC=1
CMDLINE="python3 src/main.py $1"
result=1
while [ $result -ne 0 ]; do
    $CMDLINE
    result=$?
    echo Restarting...
    sleep $SLEEP_SEC
done
