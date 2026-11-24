# Testing the reviewer's application

This guide takes you through the reviewer's application, Review desk, from signing in to a second brief that carries your earlier decisions. You play a compliance reviewer. Every step says what to do and what the page then shows, in the words the page uses, so you can check each one as you go.

The application makes live model calls through headless Claude Code, so each brief is written afresh. The counts and statements below, 9 statements resting on 16 facts with the paragraphs 7.1 to 7.3 as examples, are those of a run of section 7 of the fictional policy statement PS26/4 for the fictional Harbour Mutual Bank. Another run can return a different number of statements or facts and word the statements differently; where this guide gives a count, read your own page's count, and pick facts by the paragraph they cite.

## Open the application

1. Open `http://<host>:4802` in a browser, where `<host>` is the machine named on the hand-in page. Port 4802 is the accepted gate. The home page shows the sentence "1 topic is built: Compliance brief." and one tile, "1 Topics built".
2. Look at the bar along the top. It holds "Review desk", "Compliance brief", "Demo", "About" and "Sign in". The word "Demo" marks that the data is fictional.
3. Click "About". The sentence reads "This is a demonstration on fictional data from the hackathon starter." The page says what the data is and how a brief is made, and it ends with the product's statement about the status of its output.

## Sign in

4. Click "Sign in". The sentence reads "Sign in with your name and role to decide on a brief."
5. Type `Dana Whitfield` in "Your name" and `Head of Compliance` in "Your role", then click "Sign in". The top bar now shows "Dana Whitfield, Head of Compliance" and a "Sign out" button. Any name and role of a person will do; the application records what you type.
6. To see the refusal, click "Sign out", click "Sign in" and type `Claude` as the name and `Assistant` as the role. The page stays on the form and says "The name 'Claude' is a model, a program or a service; only a person may decide." Sign in again as Dana Whitfield.

## Start a brief on section 7

7. Click "Compliance brief" in the top bar. On a fresh application the sentence reads "No brief has been started. Choose a document and a firm to start one." and the three tiles read "0 Briefs", "0 Waiting for a reviewer" and "0 Signed". If other briefs exist, the sentence counts them, for example "1 brief so far: 1 signed."
8. Find the panel "Start a brief". "Document" shows PS26-4 and "Firm" shows Harbour Mutual Bank. All ten boxes under "Sections to read" are ticked.
9. Untick every box except "7. Incident reporting". Section 7 takes about a minute. Any section can be started, and with all ten ticked the whole document is read, which takes a few minutes, because one run makes up to 13 model calls, four at a time. The rest of this guide uses section 7.
10. Click "Start the brief". A page says the brief is being written, with a table of the sections and whether each is read, and refreshes itself every 3 seconds. While it is written, the table shows each section as "Waiting" or "Read". Starting a second brief while one is still being written is refused in words (see the last part of this guide). When the brief is ready the review page opens.

## Read the answer

11. The review page's sentence reads "The brief for Harbour Mutual Bank has 9 statements resting on 16 facts. 16 facts still need your decision before it can be signed." Under it are three tiles: "9 Statements", "0 of 16 Facts decided" with the badge "Needs a person", and "0 of 0 Questions settled".
12. Below the tiles are four tabs: "Brief", "Open questions", "Facts" and "Sign-off". The "Brief" tab is open. On the left are the nine statements, each under a heading such as "About the firm", "Third-party providers" or "Major incident reporting". Under each statement is a list of the facts it cites, for example "Paragraph 7.1, obligation" and "Row FIRM-001, firm detail", each with the badge "Needs a person".

## Open a statement's source

13. Click "Paragraph 7.1, obligation" under the statement that begins "The firm must submit an initial notification". The source panel on the right changes to "Paragraph 7.1" and the policy statement's title. It shows the paragraph, "Firms must submit an initial notification to the FSOA within 4 hours of classifying an incident as a major incident, and in any case no later than 24 hours after the incident is first detected." The words the fact quotes are marked with a grey underline. A line "Document digest" gives the digest of the paragraph.
14. Read the fields under the decision form. "Deadline as written" and "Requirement" hold what the fact says. "Known as" reads "Stated in the document". "Checks" lists "Passed The quote is word for word in the paragraph" and "Passed The deadline is word for word in the paragraph". If a check had failed, the entry would show the badge "Failed" and the brief would not cite the fact.

## Accept a fact

15. In the panel's "Your decision" group, choose "Accept". In "Your reason" type `The paragraph says this in these words.` and click "Record my decision". If you leave "Your reason" empty, the browser asks you to fill it in.
16. The panel moves to the next fact that needs a decision. The sentence now says "15 facts still need your decision before it can be signed." and the fact you decided shows the badge "Accepted by you" beside its statement.

## Amend a fact

17. Click "Paragraph 7.2, obligation". Choose "Amend". In "Amended wording, if you amend" type `Submit an intermediate report within 72 hours of the initial notification, with the cause, the services and customers affected and the actions taken.` In "Your reason" type `The cause needs the firm's wording.` and click "Record my decision". The fact shows "Amended by you". Choosing "Amend" and leaving the wording empty is refused with "Write the amended wording in your own words."

## Reject a fact

18. Click the first "Paragraph 7.3, obligation", the one under "The firm must submit a final report within 30 business days of the incident being resolved." Choose "Reject", type `The deadline needs checking with the regulator.` as the reason and click "Record my decision". The fact shows "Rejected by you".
19. Decide the 13 facts still marked "Needs a person". For each, choose "Accept", type `Matches the source.` and click "Record my decision"; the panel opens the next fact each time. When the last is recorded the sentence reads "The brief for Harbour Mutual Bank has 9 statements resting on 16 facts. You rejected 1 fact, so the brief can be returned but not signed." and the tile reads "16 of 16 Facts decided".
20. Click the "Sign-off" tab. The button "Sign the brief" is greyed out, and the message above the form reads "You rejected 1 fact that the brief cites. Return the brief so that it can be written again." The button "Return the brief" is available.

## Change a decision

21. Click the "Brief" tab and click the fact you rejected. The decision group is now headed "Change your decision", and above it the page says "Your decision: Rejected by Dana Whitfield, Head of Compliance, on" followed by the day's date and your reason.
22. Choose "Accept", type `Checked: the paragraph gives 30 business days.` and click "Record my decision". The sentence now reads "The brief for Harbour Mutual Bank has 9 statements resting on 16 facts. Every fact and question is settled, so it is ready for you to sign."

## Settle an open question

23. Click the "Open questions" tab. For this run it says "The brief carries no open questions." The engine raises a question only when the section's sub-agent cites a paragraph the section does not have, and the run of section 7 cites none. When a brief does carry one, the tab shows its text as a heading, whom to ask and its priority, then "Why it is not known", "What changes with the answer" and "Rests on", with links to the facts it rests on. Two forms follow. Fill "Your answer" and "What your answer rests on" and click "Record my answer", or fill "Or accept it as an assumption, in your words" and click "Accept as an assumption". The brief cannot be signed while a question is neither answered nor accepted, and the tile "Questions settled" counts the ones that are.

## Read the facts table

24. Click the "Facts" tab. The sentence reads "16 facts support the brief for Harbour Mutual Bank; every one has a decision." The tiles read "16 Facts", "16 of 16 Decided" and "0 Failed checks". The table has the columns "Paragraph", "Kind", "Requirement", "Deadline as written", "Checks" and "Decision". Click a column heading to sort by it, click a paragraph to open its source on the review page, and click "Export CSV" to download the rows as `facts.csv`.

## Sign the brief

25. Click the "Sign-off" tab. The text "You are acting as Dana Whitfield, Head of Compliance." shows who signs, and "Sign the brief" is now available. Leave "Why you are returning the brief, if you return it" empty and click "Sign the brief".
26. The sign-off record opens, under a tab of that name. The sentence reads "Dana Whitfield, Head of Compliance, signed the brief for Harbour Mutual Bank." The tiles read "9 Statements", "16 Decisions recorded" and "0 Assumptions accepted".

## Read the sign-off record

27. Read the record under the tiles. "Reviewer" is Dana Whitfield, "Role" is Head of Compliance, "Date" is the day's date in the form 25 November 2026, "Outcome" is Signed, and "Digest signed" is the digest of the brief you read. Below it the table "Decisions made on the brief" has one row for each of your 16 decisions, with "About", "Requirement", "Decision", "Reviewer", "Date" and "Reason". The amended fact shows "Amended:" and your wording. Click "Export CSV" to download the table as `decisions.csv`.
28. Click "Compliance brief" in the top bar. The list shows the brief, "PS26-4 for Harbour Mutual Bank, section 7", with Sections "7" and Status "Signed". If it is the only brief, the sentence reads "1 brief so far: 1 signed." "Export CSV" above the list downloads it as `briefs.csv`.

## A second run with decisions carried

29. In the "Start a brief" panel leave only "7. Incident reporting" ticked, with the same firm, and click "Start the brief". When the review page opens, the sentence reads "The brief for Harbour Mutual Bank has 9 statements resting on 16 facts. Every fact and question is settled, so it is ready for you to sign." and the tile reads "16 of 16 Facts decided".
30. Look at the badges beside the statements. Each fact shows "Carried: accepted" with the date of your earlier decision, and the fact you amended shows "Carried: amended". Hover over a badge to read "Accepted by you, on" and the date, then "Nothing judged has changed since." Click a fact: the panel says who decided and when, then "Reason given:" with your words. A decision is carried only while the fact is unchanged.
31. Click "Sign out" in the top bar, then reload the review page. It still shows the brief and its carried decisions, and in place of the decision forms it says "Sign in to decide on this fact." Nobody can decide without signing in by name and role. Sign in again as Dana Whitfield.

## Return a brief

32. On the second brief click the "Sign-off" tab. Leave "Why you are returning the brief, if you return it" empty and click "Return the brief". The page says "Write why you are returning the brief in your own words." and records nothing.
33. Type `The brief needs the root cause paragraph read again.` in that field and click "Return the brief". The sentence reads "Dana Whitfield, Head of Compliance, returned the brief for Harbour Mutual Bank." and the record shows "Outcome" Returned and "Reason for returning". The list at "Compliance brief" now reads "2 briefs so far: 1 signed, 1 returned."

## What each page's sentence means

Each page opens with one sentence that answers the question the page is for, and the tiles under it count the same things.

| Page | Question it answers | Sentence |
| --- | --- | --- |
| Home | What is built here? | "1 topic is built: Compliance brief." |
| About | What is this? | "This is a demonstration on fictional data from the hackathon starter." |
| Sign in | Who is deciding? | "Sign in with your name and role to decide on a brief." |
| Compliance brief | What is ready to brief and what waits for a person? | "3 briefs so far: 1 waiting for a reviewer, 1 signed, 1 returned." The words are "waiting for a reviewer", "being written", "signed", "returned" and "stopped". |
| A brief being written | How far has the brief got? | "The brief for Harbour Mutual Bank is being written: 1 of 1 section read." |
| A brief that stopped | Why did it stop? | "The brief for Harbour Mutual Bank stopped before it was finished." with the reason under it |
| Review | What needs my decision before I can sign? | "The brief for Harbour Mutual Bank has 9 statements resting on 16 facts." followed by what still needs a decision, or "Every fact and question is settled, so it is ready for you to sign.", or "You rejected 1 fact, so the brief can be returned but not signed." |
| Facts | Which facts does the brief rest on and where do they stand? | "16 facts support the brief for Harbour Mutual Bank; every one has a decision." or, with some undecided, "16 facts support the brief for Harbour Mutual Bank; 5 still need a decision." |
| Sign-off record | Who signed, when, and what did they decide? | "Dana Whitfield, Head of Compliance, signed the brief for Harbour Mutual Bank." or "returned" in place of "signed" |

## When something fails

| What you see | What it means and what to do |
| --- | --- |
| The page does not load | Check the address and the port, 4802, against the hand-in page. |
| "There is nothing at this address." | The address has no page. Click "Go to the home page". |
| "There is no run" followed by a number | The application was restarted and forgot its runs and decisions, which it holds in memory. Start the brief again. |
| "Sign in with your name and role to start a brief." | You are not signed in. Click "Sign in". |
| "Choose at least one section." | Tick a section in the start form. |
| "A brief is still being written. Start another when it has finished." | One run is written at a time. Wait for the review page to open for the first, then start the next. |
| "The brief for Harbour Mutual Bank stopped before it was finished." with a reason under it | A model call failed or the run could not finish. Click "Back to the briefs" and start the brief again; section 7 alone is the quickest to retry. |
| "Write your reason in your own words." | The reason is empty. Write it and record the decision again. |
| "The brief changed after you opened it, so nothing was recorded. Read it again; decisions you made on facts that did not change are kept." | The brief you were reading is no longer the current one, for example because it was open in two windows. Reload the review page and decide again. |
| "Sign the brief" is greyed out | Read the message above the form. It says how many facts have no decision or how many questions are not answered, or that you rejected a fact. |
| "Decisions on this brief were made by" followed by a name | Someone else's decisions are held on this brief. Sign in as that person to sign it, or record your own decisions again. |
