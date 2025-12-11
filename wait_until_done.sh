#!/bin/bash

# Usage: ./wait_until_done.sh "<command>" "<continue_text>"
# Example:
# ./wait_until_done.sh "sf package:install:report -i 0HfU9000003OyfeKAC -o fernando.fernandez" "InProgress"

CMD="$1"
CHECK_TEXT="$2"

if [[ -z "$CMD" || -z "$CHECK_TEXT" ]]; then
  echo "Usage: $0 \"<command>\" \"<continue_text>\""
  exit 1
fi

while true; do
  out=$(eval "$CMD" 2>&1)
  echo "$out"

  if [[ "$out" != *"$CHECK_TEXT"* ]]; then
    break
  fi

  sleep 10
done

# Audible alert when complete
afplay /System/Library/Sounds/Glass.aiff
