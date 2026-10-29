# Browse, then harvest: get the posts John opened

First used 2026-10-24 (tiendafacha.cl, new John Daystrom Instagram account in Chrome Profile 2). John: "a really
good way to get what I wanted out of an account."

John picks the posts by hand, browsing as a persona. The agent then reads that Chrome profile's history for the
exact URLs he opened and downloads them with the normal pipeline. There's no scraper, the extension isn't needed,
and the URL list is a file anyone can rerun.

## 1. John browses
Sign in with the persona in its Chrome profile, open the account, click into each post you want. Then close Chrome,
so the History file is flushed.

## 2. Pull the opened URLs from History

**Tool (2026-10-29):** `openedposts --name <account>` (`bin/ig_opened_posts.py`, wrapper `bin/wrappers/openedposts`).
Copies Profile 2's History, lists today's /p/ and /reel/ visits, and writes the raw visits, the unique list,
the History copy and SHA256SUMS to `~/Desktop/claude/<today>/claude/<account>_opened_posts/`. Options:
`--date`, `--since HH:MM`, `--until HH:MM`, `--profile DIR`, `--timeline FILE.jsonl` (check against a scrape).
It prints the `dllink --list` line to run next. By hand, the same thing is:

Chrome locks the database while it's running, so work on a copy:

    cp ~/.config/google-chrome/"Profile 2"/History /tmp/History.copy
    python3 - /tmp/History.copy <<'PY'
    import sqlite3, sys
    c = sqlite3.connect(sys.argv[1])
    for t, url in c.execute("""
        select datetime(v.visit_time/1000000-11644473600,'unixepoch','localtime'), u.url
        from visits v join urls u on u.id = v.url
        where (u.url like '%instagram.com/p/%' or u.url like '%instagram.com/reel/%')
          and v.visit_time/1000000-11644473600 > strftime('%s','now','-3 hours')
        order by v.visit_time"""):
        print(t, url.split('?')[0])
    PY

Remove duplicates, write one URL per line to a list file in the day folder, and add sha256 for it.

## 3. Cookies to a named file
Use a new file per persona. Never overwrite another persona's file:

    ~/miniforge3/envs/dl_wm/bin/python bin/export_browser_cookies.py instagram.com conf/instagram.cookies.<persona>.txt
    ~/miniforge3/envs/dl_wm/bin/python bin/check_cookie_file.py conf/instagram.cookies.<persona>.txt

(Profile 2 is the default. Pass the profile dir as the 3rd argument for another one.) Then put the file first under
`cookie_hierarchy.instagram` in `conf/app_config.json`. `conf/instagram.cookies.*.txt` is gitignored.

## 4. Download
    dllink --list <list file>

It waits 60-180 s between links, and Ctrl-C is safe (re-run carries on). Posts that are only images may fail.
