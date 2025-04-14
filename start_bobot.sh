#!/bin/bash
CMDLINE='python src/main.py cfg/periodic.json'
result=1
while [ $result -ne 0 ]; do
    $CMDLINE
    result=$?
    echo Restarting...
    sleep 10
done
