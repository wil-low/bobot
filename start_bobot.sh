#!/bin/bash
CMDLINE="python3 src/main.py $1"
result=1
while [ $result -ne 0 ]; do
    $CMDLINE
    result=$?
    echo Restarting...
    sleep 10
done
