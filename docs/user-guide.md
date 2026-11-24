# Testing the reviewer's application

This guide takes you through the reviewer's application, Review desk, from signing in to a second brief that carries your earlier decisions. You play a compliance reviewer. Every step says what to do and what the page then shows, in the words the page uses, so you can check each one as you go.

The server at the accepted gate starts with two briefs already made, both runs of section 7 of the fictional policy statement PS26/4 for the fictional Harbour Mutual Bank: one waiting for a reviewer, which you work through, and one already signed by Dana Whitfield, Head of Compliance. Any brief you start yourself later is written afresh through live model calls with headless Claude Code, so another run returns a different number of statements and facts, words the statements differently and groups them under other headings. Where this guide names a count, the page shows its own; where it names a fact, pick it by the paragraph it cites, such as "Paragraph 7.1, obligation". Facts about the firm and its providers are named in words, for example "Harbour Mutual Bank, firm profile: total assets".

## Open the application

1. Open `http://<host>:4802` in a browser, where `<host>` is the machine named on the hand-in page. Port 4802 is the accepted gate. The home page leads with what waits for a reviewer, in a sentence such as "1 brief is waiting for a reviewer." Under it is one tile for each workflow that is built, headed by the workflow's name and giving how many items of it are waiting; a tile opens that workflow's list.
2. Look at the bar along the top. It holds "Review desk", "Compliance brief", "Demo", "About" and "Sign in". The word "Demo" marks that the data is fictional.
3. Click "About". The sentence reads "This is a demonstration on fictional data from the hackathon starter." The page says what the data is and how a brief is made, and it ends with the product's statement about the status of its output.

## Sign in

4. Click "Sign in". The sentence reads "Sign in with your name and role to decide on a brief."
5. Type `Dana Whitfield` in "Your name" and `Head of Compliance` in "Your role", then click "Sign in". The top bar now shows "Dana Whitfield, Head of Compliance" and a "Sign out" button. Any name and role of a person will do; the application records what you type.
6. To see the refusal, click "Sign out", click "Sign in" and type `Claude` as the name and `Assistant` as the role. The page stays on the form and says "The name 'Claude' is a model, a program or a service; only a person may decide." Sign in again as Dana Whitfield.

## Open the waiting brief

7. Click "Compliance brief" in the top bar, or the tile of that name on the home page. The sentence counts the briefs and says how many wait for a reviewer and how many are signed, and the three tiles read "Briefs", "Waiting for a reviewer" and "Signed". The list names each brief, for example "PS26-4 for Harbour Mutual Bank, section 7", with its Sections and its Status. On a server that starts empty the sentence reads "No brief has been started. Choose a document and a firm to start one."; start one as the last part of this guide describes, and come back.
8. Click the brief whose Status is "Waiting for a reviewer". The review page opens.

## Read the answer

9. The review page's sentence reads "The brief for Harbour Mutual Bank has" some number of statements "resting on" some number of facts, then says how many facts still need your decision before it can be signed. Under it are three tiles. "Statements" counts the statements. "Facts decided" shows how many of the facts the brief cites are decided, as "0 of" their number, with the badge "Needs a person". "Questions settled" shows "0 of 0".
10. Below the tiles are tabs: "Brief", "Firm profile", "Open questions", "Facts" and "Sign-off". The "Brief" tab is open. At the top left is a picture of the document: one small box for each paragraph read, in the document's order under its section's heading, with the paragraph's number and a word for what was found in it, such as "Obligation, deadline", "Obligation" or "No fact"; "Open question" and "Failed check" show in amber and coral, with an icon. A line above it says how many paragraphs are accounted for, for example "5 of 5 paragraphs of section 7 accounted for". Under the picture are the statements, each under a heading the run chose, and under each statement the facts it cites, for example "Paragraph 7.1, obligation", each with the badge "Needs a person".

## Open a source

11. Click a paragraph box in the picture, such as "7.1". The source panel on the right changes to "Paragraph 7.1" and the policy statement's title. A paragraph with no fact opens its text and says why no fact was read from it. Click "Paragraph 7.1, obligation" under the statement that cites it, and the same panel shows the paragraph, "Firms must submit an initial notification to the FSOA within 4 hours of classifying an incident as a major incident, and in any case no later than 24 hours after the incident is first detected." The words the fact quotes are marked with a dark underline on a grey fill. A line "Document digest" gives the digest of the document. The decision form sits under the paragraph, so the reason box and the button are in view without scrolling the panel.
12. Read the fields under the decision form. "Deadline as written" and "Requirement" hold what the fact says. "Known as" reads "Stated in the document". "Checks" lists "Passed The quote is word for word in the paragraph" and "Passed The deadline is word for word in the paragraph". If a check had failed, the entry would show the badge "Failed" and the brief would not cite the fact.

## Decide the firm profile

13. Click the "Firm profile" tab. The block "The firm profile the brief was written against" lists, in words, what the brief states about the firm and then about each provider: the firm's name, type, customers and total assets, a field the firm table leaves empty as "none named", and each provider by its name with its service and contract. Each row has a badge and a "Source" link. Click a "Source" link: the row opens on the right as a table of field and value, with the quoted field marked.
14. Below the block is one decision form for the whole profile. Choose "Accept", type `The firm and provider tables say this.` in "Your reason" and click "Record my decision about the profile". Every row now shows "Accepted by you", and the block says "Accepted by you, on" the day's date, "covering" the number of facts the profile holds, with your reason. The firm and provider facts are not decided one by one. Choosing "Amend" shows the box "Amended profile, in your words"; leaving it empty is refused with "Write the amended wording in your own words." The page then opens the first paragraph fact that still needs a decision.

## Accept a fact

15. In the panel's "Your decision" group, choose "Accept". In "Your reason" type `The paragraph says this in these words.` and click "Record my decision". If you leave "Your reason" empty, the browser asks you to fill it in.
16. The panel moves to the first fact that still needs a decision. The sentence now says one fewer fact still needs your decision, and the fact you decided shows the badge "Accepted by you" beside its statement.

## Amend a fact

17. Click "Paragraph 7.2, obligation". Choose "Amend"; the box "Amended wording, if you amend" appears. Type `Submit an intermediate report within 72 hours of the initial notification, with the cause, the services and customers affected and the actions taken.` In "Your reason" type `The cause needs the firm's wording.` and click "Record my decision". The fact shows "Amended by you". Choosing "Amend" and leaving the wording empty is refused: the page stays on that fact and says "Write the amended wording in your own words." beside the form, with your reason kept.

## Reject a fact

18. Click a fact named "Paragraph 7.3, obligation"; if two carry that name, the first. Choose "Reject", type `The deadline needs checking with the regulator.` as the reason and click "Record my decision". The fact shows "Rejected by you".
19. Decide every paragraph fact still marked "Needs a person". For each, choose "Accept", type `Matches the source.` and click "Record my decision"; the panel opens the first fact still waiting each time. When the last is recorded the sentence ends "You rejected 1 fact, so the brief can be returned but not signed." and the tile "Facts decided" shows the same number on both sides of "of".
20. Click the "Sign-off" tab. The button "Sign the brief" is greyed out, and the message above the form reads "You rejected 1 fact that the brief cites. Return the brief so that it can be written again." The button "Return the brief" is available.

## Change a decision

21. Click the "Brief" tab and click the fact you rejected. The decision group is now headed "Change your decision", and above it the page says "Your decision: Rejected by Dana Whitfield, Head of Compliance, on" followed by the day's date and your reason.
22. Choose "Accept", type `Checked: the paragraph gives 30 business days.` and click "Record my decision". The sentence now ends "Every fact and question is settled, so it is ready for you to sign."

## Settle an open question

23. Click the "Open questions" tab. For this brief it says "The brief carries no open questions." The engine raises a question only when the section's sub-agent cites a paragraph the section does not have, and the run of section 7 cites none. When a brief does carry one, the tab shows its text as a heading, whom to ask and its priority, then "Why it is not known", "What changes with the answer" and "Rests on", with links to the facts it rests on. Two forms follow. Fill "Your answer" and "What your answer rests on" and click "Record my answer", or fill "Or accept it as an assumption, in your words" and click "Accept as an assumption". The brief cannot be signed while a question is neither answered nor accepted, and the tile "Questions settled" counts the ones that are.

## Read the facts table

24. Click the "Facts" tab. The sentence says how many facts support the brief for Harbour Mutual Bank and that every one has a decision. The tiles read "Facts", "Decided" and "Failed checks"; "Decided" shows the same number on both sides of "of" and "Failed checks" shows 0. The picture of the document leads the page, and the table is below it, with the columns "Source", "Kind", "Requirement", "Deadline as written", "Checks" and "Decision". Click a column heading to sort by it, click a source to open it on the review page, and click "Export CSV" to download the rows as `facts.csv`.

## Sign the brief

25. Click the "Sign-off" tab. The text "You are acting as Dana Whitfield, Head of Compliance." shows who signs, and "Sign the brief" is now available. Leave "Why you are returning the brief, if you return it" empty and click "Sign the brief".
26. The sign-off record opens, under a tab of that name. The sentence reads "Dana Whitfield, Head of Compliance, signed the brief for Harbour Mutual Bank." The tiles read "Statements", "Decisions recorded" and "Assumptions accepted". "Statements" counts the statements of the brief you read, "Decisions recorded" counts the decisions the table below lists, and "Assumptions accepted" is 0.

## Read the sign-off record

27. The page reads in this order. First the sentence. Then the brief as it was signed: each statement with the facts it cites and the decision each fact stands on. Click a fact there, or a paragraph box in the facts table's picture, to read its source beside the statements, with the decision and the reason that settled it. The page offers no form, so nothing on a signed brief can be changed. Then the sign-off record: "Reviewer" is Dana Whitfield, "Role" is Head of Compliance, "Date" is the day's date in the form 25 November 2026, "Outcome" is Signed, and "Digest signed" shows the start of the digest of the brief you read; hover over it, or tab to it and press Enter, to read the whole value. Last, the table "Decisions made on the brief" has one row for each decision, with "About", "Requirement", "Decision", "Reviewer", "Date" and "Reason". The firm profile is one row, "Firm profile" with the number of facts it covered and their names, because you decided it once. The amended fact shows "Amended:" and your wording. Click "Export CSV" to download the table as `decisions.csv`.
28. Click "Compliance brief" in the top bar. The list now shows both briefs with Status "Signed". The sentence counts them, for example "2 briefs so far: 2 signed." "Export CSV" above the list downloads it as `briefs.csv`.

## Start a brief of your own

29. Find the panel "Start a brief". "Document" shows PS26-4 and "Firm" shows Harbour Mutual Bank. All ten boxes under "Sections to read" are ticked. Untick every box except "7. Incident reporting". Section 7 takes about a minute. Any section can be started, and with all ten ticked the whole document is read, which takes a few minutes, because one run makes up to 13 model calls, four at a time.
30. Click "Start the brief". A page says the brief is being written, with a table of the sections and whether each is read, and refreshes itself every 3 seconds. While it is written, the table shows each section as "Waiting" or "Read". Starting a second brief while one is still being written is refused in words (see the last part of this guide). When the brief is ready the review page opens.

## A second run with decisions carried

31. The model words some facts differently on each run, so this brief is a new draft and not a copy of the first. When the review page opens, the sentence says how many facts still need your decision. It may say all, some or none, depending on how many facts the model worded as it did before.
32. Look at the badges beside the statements. A fact whose judged content is the same as the one you decided shows "Carried: accepted", or "Carried: amended" for one you amended, with the date of your earlier decision. Hover over a badge to read "Accepted by you, on" and the date, then "Nothing judged has changed since." Click a carried fact: the panel says who decided and when, then "Reason given:" with your words. A fact the model has worded differently, for example a requirement put another way, is asked again. It shows "Needs a person", and its panel shows your earlier decision, who made it, when and why, then "Since then these changed:" with the part that changed, such as "Requirement". Decide it again. This is the design: a decision is carried only while the fact's judged content is unchanged. The "Firm profile" tab shows the same: the profile is settled when every fact in it is.
33. Click "Sign out" in the top bar, then reload the review page. It still shows the brief and its carried decisions, and in place of the decision forms it says "Sign in to decide on this fact." Nobody can decide without signing in by name and role. Sign in again as Dana Whitfield.

## Return a brief

34. On the new brief click the "Sign-off" tab. Leave "Why you are returning the brief, if you return it" empty and click "Return the brief". The page says "Write why you are returning the brief in your own words." and records nothing. A brief can be returned whether or not every fact has a decision.
35. Type `The brief needs the root cause paragraph read again.` in that field and click "Return the brief". The sentence reads "Dana Whitfield, Head of Compliance, returned the brief for Harbour Mutual Bank." and the record shows "Outcome" Returned, "Digest returned" and "Reason for returning". The list at "Compliance brief" now counts the returned brief.

## What each page's sentence means

Each page opens with one sentence that answers the question the page is for, and the tiles under it count the same things.

| Page | Question it answers | Sentence |
| --- | --- | --- |
| Home | What waits for a reviewer? | "1 brief is waiting for a reviewer." or, with several workflows, each workflow's count in one sentence |
| About | What is this? | "This is a demonstration on fictional data from the hackathon starter." |
| Sign in | Who is deciding? | "Sign in with your name and role to decide on a brief." |
| Compliance brief | What is ready to brief and what waits for a person? | "3 briefs so far: 1 waiting for a reviewer, 1 signed, 1 returned." The words are "waiting for a reviewer", "being written", "signed", "returned" and "stopped". |
| A brief being written | How far has the brief got? | "The brief for Harbour Mutual Bank is being written: 1 of 1 section read." |
| A brief that stopped | Why did it stop? | "The brief for Harbour Mutual Bank stopped before it was finished." with the reason under it |
| Review | What needs my decision before I can sign? | "The brief for Harbour Mutual Bank has" its statements and facts, followed by what still needs a decision, or "Every fact and question is settled, so it is ready for you to sign.", or "You rejected 1 fact, so the brief can be returned but not signed." |
| Facts | Which facts does the brief rest on and where do they stand? | "These facts support the brief for Harbour Mutual Bank; every one has a decision." or, with some undecided, the same sentence ending "5 still need a decision." |
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
| "Write the amended wording in your own words." | You chose "Amend" and left the wording empty. The page stays on that fact; write the wording, or choose another outcome, and record the decision again. |
| "The brief changed after you opened it, so nothing was recorded. Read it again; decisions you made on facts that did not change are kept." | The brief you were reading is no longer the current one, for example because it was open in two windows. Reload the review page and decide again. |
| "Sign the brief" is greyed out | Read the message above the form. It says how many facts have no decision or how many questions are not answered, or that you rejected a fact. |
| "Decisions on this brief were made by" followed by a name | Someone else's decisions are held on this brief. Sign in as that person to sign it, or record your own decisions again. |
