# Sources of the regulations

The second dataset of topic 03 reads three regulations: Regulation (EU) 2022/2554 (DORA), Regulation (EU) 2024/1689 (the AI Act) and the Prudential Regulation Authority's Supervisory Statement SS1/23.

The texts of DORA and the AI Act are held in `texts/`, byte for byte as the Publications Office served them, with the source acknowledged as its copyright notice, quoted below, describes. The text of SS1/23 is not held: its publisher's terms allow personal and internal non-commercial use only, so the repository holds its address and digest, and `python -m context.regulations fetch` fetches it into `cache/`, a folder git ignores. Every text is checked against the digest below before it is read, and a difference stops the read.

## What is recorded for each regulation

| | DORA | The AI Act | SS1/23 |
| --- | --- | --- | --- |
| Title | Regulation (EU) 2022/2554 of 14 December 2022 on digital operational resilience for the financial sector | Regulation (EU) 2024/1689 of 13 June 2024 laying down harmonised rules on artificial intelligence | Supervisory Statement SS1/23, Model risk management principles for banks, the version of 23 April 2026 that updates the May 2023 statement |
| Publisher | Publications Office of the European Union | Publications Office of the European Union | Prudential Regulation Authority |
| Version read | Official Journal L 333, 27 December 2022, as published | Official Journal L series, 12 July 2024, as published | Published 23 April 2026, effective from 23 April 2026 (the PDF's cover is dated 16 April 2026, "updating 17 May 2023") |
| Address fetched | https://publications.europa.eu/resource/celex/32022R2554 | https://publications.europa.eu/resource/celex/32024R1689 | https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/supervisory-statement/2026/liaf0126app5.pdf |
| Format | XHTML, asked for with `Accept: application/xhtml+xml` and `Accept-Language: en` | XHTML, asked for in the same way | PDF, 31 pages |
| Date fetched | 25 November 2026 | 25 November 2026 | 25 November 2026 |
| Size | 746,866 bytes | 1,262,391 bytes | 513,641 bytes |
| SHA-256 digest | sha256:cf50d8f023d23b2a56f535aaee0760eba7f1925ef08a9858c5c31d43d414f46b | sha256:8f0b656302f9864cc87e040c371f209a9d65ae1a6cecc25ca5eb737e872d721a | sha256:14a12b480537959013dcc9153f4193d459b7d3ecda14903759b76ab4d7ff24fb |
| Held in the repository | `texts/dora.xhtml`, unchanged | `texts/ai-act.xhtml`, unchanged | No; fetch script and digest only |
| Terms | see the notice quoted below | see the notice quoted below | Personal and internal non-commercial use |

Both EU addresses answer with a redirect to the document in the Publications Office's own store, for example `https://publications.europa.eu/resource/cellar/0caf473a-85bd-11ed-9887-01aa75ed71a1.0006.03/DOC_1` for DORA and `https://publications.europa.eu/resource/cellar/dc8116a1-3fe6-11ef-865a-01aa75ed71a1.0006.03/DOC_1` for the AI Act. The `http` and `https` forms of each address gave the same bytes. The act as first published is read; later consolidated versions and corrigenda are not. Fetched a second time at 07:07 UTC on 25 November 2026, all three digests were the same as at the first fetch about fifty minutes earlier. `python -m context.regulations verify` repeats that check against the publishers.

The Prudential Regulation Authority's page for SS1/23, at https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks-ss, lists two versions. The version of 23 April 2026 is current. The May 2023 version, https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/supervisory-statement/2023/ss123.pdf, is recorded in `sources.json` with its digest (sha256:6165a8ba699e9c7ffb6a693711f6a07b555021aa823e1a79582d9bc2e8052de7, 1,096,596 bytes) and is not read. The April 2026 text still says in paragraph 1.5 that the policy comes into effect on 17 May 2024.

## Notice for the EU texts

The Publications Office's copyright notice, https://op.europa.eu/en/web/about-us/legal-notices/publications-office-of-the-european-union-copyright, opened on 25 November 2026 (HTTP 200), says: "The editorial content of this website, which is owned by the EU, is licensed under the Creative Commons Attribution 4.0 International licence. This means that you can reuse it provided you acknowledge the source and indicate any changes you have made." It also says: "Most of the publications on this website are freely available, many of them under Creative Commons licences, and can be downloaded and reproduced provided the source is acknowledged." The first quotation leaves out one thing between its two sentences: the link label "(external link)", which the notice page shows after the first sentence's last words; no words are missing. The notice heads its text "© European Union, 2026".

This note claims nothing beyond those words. The texts were fetched from the addresses in the table on the date in the table, and each digest there is the digest of the bytes held in `texts/`.

Attribution for each text: © European Union. DORA is Official Journal of the European Union, OJ L 333, 27.12.2022, p. 1, from the Publications Office of the European Union at https://publications.europa.eu/resource/celex/32022R2554. The AI Act is Official Journal of the European Union, OJ L, 2024/1689, 12.7.2024, from the Publications Office of the European Union at https://publications.europa.eu/resource/celex/32024R1689.

The text is split into units for reading and no wording is altered. The check that proves it is `test_every_source_paragraph_is_found_word_for_word_in_the_units` in `tests/regulations/test_regulations_real_text.py`: every paragraph of each act, with its footnote references and its own number taken out, is found word for word in the units' text, or is a point label, a heading or page furniture of a named kind. Units, anchors and the other records in this repository are derived from the texts and are the repository's own work.

The legal notice of EUR-Lex is at https://eur-lex.europa.eu/content/legal-notice/legal-notice.html, where a reader checks the terms. This address is taken from the Publications Office's notice, which links to it, and it was not opened by this reader: an automated request to it got HTTP status 202 with an empty body, a challenge page, so it is unreadable here. The reader does not pass the challenge, and EUR-Lex is not used as a source.

## Terms of SS1/23

The legal terms of the publisher's site, https://www.bankofengland.co.uk/legal, read on 25 November 2026, say: "Unless otherwise stated, the copyright and any other rights in the contents of the Resources, including but not limited to images, text and data, are owned by the Governor and Company of [the publisher]." They allow a reader to "download, display or print the Resources for personal use or internal use within an individual organisation for non-commercial purposes", and add: "The Bank typically grants permission for non-commercial re-use of the Resources, particularly in an academic or education context." Permission to reproduce is asked for on a form: "If you would like to request permission to reproduce, use or link to [the publisher] material, please complete our request permission to use [the publisher] material form." The publisher's name is replaced by "[the publisher]" in these quotations because the repository's guard refuses it. The PDF's cover carries "© [the publisher] 2026".

The statement's text, its page headers included, is therefore not committed, and neither is any recording that carries it.

## Software the readers need

The two EU texts are read with the Python standard library alone. SS1/23 is a PDF, and its reader needs poppler's `pdftotext`, because a page's text alone cannot tell a footnote marker or a heading from body text; on Debian and Ubuntu it is in the package `poppler-utils`. `python -m context.regulations fetch` checks for it before fetching and stops with that instruction when it is missing, and the reader gives the same message.

## Every address requested

| Address | Result |
| --- | --- |
| https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32022R2554 | HTTP 202, empty body, challenge page; unreadable and unused |
| http://publications.europa.eu/resource/celex/32022R2554 | HTTP 303 to the document, then 200; the same bytes as the https address |
| https://publications.europa.eu/resource/celex/32022R2554 | 200 with the digest above, used |
| http://publications.europa.eu/resource/celex/32024R1689 | 200; the same bytes as the https address |
| https://publications.europa.eu/resource/celex/32024R1689 | 200 with the digest above, used |
| https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks-ss | 200; read for the two versions |
| https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/supervisory-statement/2026/liaf0126app5.pdf | 200 with the digest above, used |
| https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/supervisory-statement/2023/ss123.pdf | 200, digest recorded and text unread |
| https://op.europa.eu/en/web/about-us/legal-notices/publications-office-of-the-european-union-copyright | 200, read on 25 November 2026 at about 06:20 and again at 07:07 UTC |
| https://eur-lex.europa.eu/content/legal-notice/legal-notice.html | 202, empty body, challenge page; unreadable |
| https://commission.europa.eu/legal-notice_en | 200, read for background |
| https://publications.europa.eu/resource/celex/32011D0833 | 200, read for background; the Commission's reuse decision covers documents the Commission produces |
| https://op.europa.eu/en/web/about-us/legal-notices/eur-lex-european-union-law | 404, an address that does not exist |
| https://www.bankofengland.co.uk/legal | 200, read for the terms of SS1/23 |

## What each regulation reads into

Each is read by its own structure into units that a fact can cite, and the units are pinned in `expected/` by anchor, kind and the digest of their text, so a later read of the same bytes must give the same units. The counts below close: every text element of each document is placed in a unit, a heading or a named class of page furniture, or the read stops.

The reader's article counts agree with the Publications Office's own: 64 articles for DORA and 113 for the AI Act, each numbered from 1 with no gap, and 106 and 180 recitals likewise.

| | DORA | The AI Act | SS1/23 |
| --- | --- | --- | --- |
| Chapters | 9 | 13 | 4 |
| Sections | 6 | 16 | none |
| Articles | 64 | 113 | none |
| Annexes | none | 13 | none |
| Principles and sub-principles | none | none | 5 and 23 |
| Recitals | 106 | 180 | none |
| Citations of the preamble | 6 | 7 | none |
| Article paragraphs, definitions and other article units | 349 | 593 | none |
| Annex units | none | 91 | none |
| Numbered paragraphs | none | none | 32 |
| Principle overviews, statements, leads and points | none | none | 5, 5, 7 and 82 |
| Closing formula | 1 | 1 | none |
| Footnotes | 39 | 58 | 23 |
| Units in all | 501 | 930 | 154 |
