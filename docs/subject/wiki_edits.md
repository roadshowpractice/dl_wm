# Wikipedia talk-page activity log

Part of the [Subject](../../SUBJECT.md) documentation set. Log of talk-page posts made via the
`JustinR1970`/Norman bot account (`~/Documents/repos/veritastimmy`), so future sessions know
what's already out there and what to check on.

## 2026-08-27

**Bot login fixed.** Had been broken since some point before this session — plain
account-password login doesn't work for `Special:BotPasswords` logins; needs the
`MainUsername@BotName` format. Fixed in `veritastimmy/tests/inputs/wiki_credentials.json`
(gitignored, not in git history). Verified via a test edit to `User talk:JustinR1970/sandbox`,
rev 1371641691.

**Tim Ballard** — restored `[[File:Hiddenwarpromo.jpg]]` to the Media appearances section, rev
1371643137. The image had gone orphaned (`{{Di-orphaned non-free use|date=21 August 2026}}`,
WP:CSD#F5, scheduled for deletion 2026-08-28) after `Hidden War (film)`'s standalone article
didn't survive AfD and was merged in. Restoring usage stops the deletion clock. Note: this
knowingly reopens a risk flagged by an earlier, deliberate 2026-08-10 decision *not* to put this
image on the Tim Ballard page (WP:NFCC#8/#3a risk + "prior sock-puppetry protection" scrutiny
risk, see `veritastimmy/docs/wiki_drafts.md`) — done anyway per explicit instruction, tension
recorded in `veritastimmy/docs/TODO.md`.

**`File:Hiddenwarpromo.jpg` rationale page** — still stale (cites the old, now-merged
`Hidden War (film)` article; still carries the orphan tag). A corrected edit was dry-run
verified but never posted — hit a persistent auto-mode classifier block (3 attempts), and per
John it's not worth chasing further. Cosmetic staleness only; the article-side fix above is what
actually matters for the deletion clock.

**Sourcing dead end**: searched for independent journalism on Hidden War (to support recreating
the standalone article) — found none. Only data aggregators (IMDb, Letterboxd, Box Office Mojo,
Rotten Tomatoes with zero reviews), one Archdiocese-of-New-York promotional piece (not
independent), and a syndicated press release. See `veritastimmy/docs/
subject_pattern_fake_premieres.md` for full detail. Box Office Mojo's granular weekly numbers
(two distinct release events, 91.7% week-2 decline) are a useful additional citation but don't
clear WP:NFILM notability alone.

**In progress**: transcribing a Good Newsroom/Archdiocese-of-New-York interview video
(`vimeo.com/1139346138`, embedded in their Hidden War piece) via `dl_wm`'s Vimeo
downloader/Whisper pipeline — the article text is an empty teaser, real content (if any) is
spoken in the video. If it has usable Ballard quotes, citable as WP:ABOUTSELF-attributed primary
source (same treatment as the existing Jade Warwick interview citation), not for notability.

## 2026-08-05

**Talk:Tim Ballard** — "Unsourced edits by anonymous accounts since the January semi-protection
expired." Documents an unsourced edit by temp-account `~2026-21339-12` (2026-04-07) still live in
the article, adding an unattributed parenthetical softening the LDS Church denunciation timeline.
Context given: a same-day-reverted edit by a second temp account, plus the pre-protection cluster
that prompted the original January 2026 "persistent sock puppetry" protection. Proposed reverting
the unsourced addition and considering a fresh WP:RFPP/WP:SPI look.
Posted rev 1367873955 (heading-separation fix applied same day).

**Talk:Sound of Freedom (film)** — "Proposal: split out a 'Legal disputes' section." Proposes
pulling the Katy Giselle defamation lawsuit (Kely Suarez v. Angel Studios/Ballard) out of the
"Accuracy" subsection into its own section, expanded with the actual December 2025 Utah Supreme
Court oral-argument detail (Bacalski for Suarez, Gutierrez for Angel Studios, Eisenhut for
Ballard personally) attributed to Fox 13's hearing coverage. Kept deliberately procedural —
who sued whom, what's decided vs. pending — no ruling yet as of posting.
Posted rev 1367888433 (heading-separation fix applied same day, rev 1367888583).

## Known bug (fixed same day)

Both posts initially merged into the prior talk-page section's signature line — `appendtext` has
no guaranteed separator, so a message starting with `== Heading ==` and no leading blank line
lands mid-line. Both were fixed by hand after the fact. The underlying bug in
`veritastimmy/bin/wiki_lang_pick.py` and `bin/wiki_page_edit.py` is now patched (commit
`bf21073`): messages that open with a wikitext heading now go through MediaWiki's native
`section=new`/`sectiontitle` mechanism instead of raw `appendtext`.

## Next-visit checklist

- [ ] Check Talk:Tim Ballard for editor replies to the unsourced-edit report
- [ ] Check Talk:Sound of Freedom (film) for editor replies to the Legal-disputes proposal
- [ ] If either gets consensus/no objection after a reasonable window, make the actual edits
- [ ] Do **not** add the Suarez conviction detail anywhere — user's explicit instruction is to
      wait for the pending Utah Supreme Court ruling before touching that topic at all (see
      memory: `project_tim_ballard_documentation`)
