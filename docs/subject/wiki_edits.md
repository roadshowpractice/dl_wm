# Wikipedia talk-page activity log

Part of the [Subject](../../SUBJECT.md) documentation set. Log of talk-page posts made via the
`JustinR1970`/Norman bot account (`~/Documents/repos/veritastimmy`), so future sessions know
what's already out there and what to check on.

## 2026-09-17

**Source staged, not yet drafted into article text.** Downloaded + transcribed a Facebook video
posted by Tim Ballard (`officialtimballard`), Sept 17 2026, "Part 2 of 2" of a pair marking the
third anniversary of what he calls "Defamation Day" (Sept 15). Local copy:
`outputs/manual/1780261423101922_Video_wm.mp4`, transcript `outputs/manual/
1780261423101922_Video_wm.srt`. Self-published, WP:ABOUTSELF only — cite as "Ballard said/
announced X," never as fact.

Citable content identified: Ballard announces a sequel, **"Backfire 2,"** exact quote —
"So Backfire 2 is going to be coming out." — no release date, platform, or further detail given
anywhere else in the video. This is the only new-release announcement in the transcript; worth a
line in the Media appearances / filmography area alongside the existing Backfire /
`File:Hiddenwarpromo.jpg` material once there's more than a one-line announcement to source (a
bare "coming out" mention with no date is thin).

**Deliberately not drafted:** the same video contains extensive, uncorroborated allegations
naming a podcaster ("Jason Preston") and a second podcaster (name unclear on transcription,
possibly "Leonard H. Chad") plus claims that multiple LDS stake presidents were excommunicated
for refusing orders related to Ballard's own case. These are BLP-risk claims about identifiable
third parties, not just self-reporting about Ballard — held back this session per explicit
instruction, not drafted into any page or talk-page proposal. A companion video from the same
day (Katherine Ballard, "Part 1 of 2") was reviewed in the same session and is also being held
back in full (see [[feedback_tim_ballard_wiki_legal_caution]]-adjacent caution — one line in it
gestures at "my husband's innocence proven in court," which sits close enough to the still-
pending Suarez v. Ballard matter to warrant the same wait-for-ruling treatment).

## 2026-08-31

**Sound of Freedom (film)** — added a paragraph to `===Accuracy===`, rev
`1372477709`, via `wiki_replace_edit.py` (dry-run verified first). Sourced
to Noticias Caracol (Colombian TV), independent journalism, not
Ballard-self-report: the real "Operación Cristal 2" sting (Cartagena, Oct
2014) that inspired the film — 54 minors rescued (corroborates the film's
own number, which the existing article text already has Ballard disputing
upward to 123), 5 prosecuted/4 convicted/16-year sentences/1 acquitted, and
the detail not present anywhere else in this project's material: sentences
upheld on appeal a decade later but all four convicted traffickers
currently free on expired legal deadlines, authorities seeking to
recapture them. Full research trail: `veritastimmy/docs/tb_cartagena_sources_2026-08-31.md`,
`tb_untouched_batch_wiki_claim_sort_2026-08-31.md` (this fact went through
a same-day correction cycle — downgraded as unconfirmed against written
recap articles, then restored after being verified word-for-word against
the broadcast's own SRT — see that doc's update notes). Does not touch the
Suárez v. Angel Studios/Ballard defamation case (separate, still-guarded
topic, see [[feedback_tim_ballard_wiki_legal_caution]]) — this is her
unrelated, already-concluded criminal trafficking case from the same
underlying operation.

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

**Done**: transcribed the Good Newsroom/Archdiocese-of-New-York interview video
(`vimeo.com/1139346138`, embedded in their Hidden War piece) via `dl_wm`'s Vimeo
downloader/Whisper pipeline — `outputs/2026-08-27/vimeo__1139346138/vimeo__1139346138.txt`.
Not an empty teaser like the article text: real, specific claims from Ballard on camera —
an origin story ("aerial recovery" claiming 3,000 children/people rescued across 6 countries,
prompted by his wife's Ukraine-adoption foundation), an explicit self-comparison to Sound of
Freedom ("one country, Colombia... this is six countries"), and an unverified statistic ("80%
of kids who disappear... recruited from their own cell phones"). Citable only as
WP:ABOUTSELF-attributed claims ("Ballard said..."), same treatment as the existing Jade Warwick
interview citation — not for notability, not stated as fact. Deliberately not drafted into
article text yet; see `veritastimmy/docs/TODO.md` for the open decision.

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
