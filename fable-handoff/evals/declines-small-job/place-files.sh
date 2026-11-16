#!/usr/bin/env bash
set -eu
cp -R "$(dirname "$0")/files/." .
git init -q -b main 2>/dev/null || git init -q
git add -A
git -c user.email=eval@example.com -c user.name=eval commit -qm init
