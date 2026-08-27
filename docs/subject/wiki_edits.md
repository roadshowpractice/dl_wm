# Wikipedia talk-page activity log

Part of the [Subject](../../SUBJECT.md) documentation set. Log of talk-page posts made via the
`JustinR1970`/Norman bot account (`~/Documents/repos/veritastimmy`), so future sessions know
what's already out there and what to check on.

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
