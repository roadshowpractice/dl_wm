#!/usr/bin/env python3
import json, sys
from datetime import timedelta

if len(sys.argv) < 2:
    print("usage: short_srt.py file.json", file=sys.stderr)
    sys.exit(1)

data = json.load(open(sys.argv[1], encoding="utf-8"))

def fmt(t):
    td = timedelta(seconds=t)
    total = int(td.total_seconds())
    ms = int((t - total) * 1000)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

i = 1

for seg in data["segments"]:

    # CASE 1: word-level timestamps exist
    if "words" in seg:

        words = seg["words"]
        for j in range(0, len(words), 2):

            chunk = words[j:j+2]

            start = chunk[0]["start"]
            end   = chunk[-1]["end"]

            text = " ".join(w["word"].strip() for w in chunk)

            print(i)
            print(f"{fmt(start)} --> {fmt(end)}")
            print(text)
            print()

            i += 1


    # CASE 2: only segment-level timestamps exist
    else:

        words = seg["text"].split()

        dur = seg["end"] - seg["start"]
        step = dur / len(words)

        for j in range(0, len(words), 2):

            chunk = words[j:j+2]

            start = seg["start"] + j*step
            end   = seg["start"] + (j+len(chunk))*step

            text = " ".join(chunk)

            print(i)
            print(f"{fmt(start)} --> {fmt(end)}")
            print(text)
            print()

            i += 1
