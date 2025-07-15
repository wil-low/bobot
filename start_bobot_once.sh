#!/bin/bash
CMDLINE="python3 src/main.py $1"
$CMDLINE 1> log/output.txt 2>&1 &
