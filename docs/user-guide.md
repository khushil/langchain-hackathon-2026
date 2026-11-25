# Testing the reviewer's application

This guide takes you through the reviewer's application, Review desk, from starting it to a second brief that carries earlier decisions. You play a compliance reviewer. Every step says what to do and what the page then shows, in the words the page uses, so you can check each one as you go.

The application keeps its briefs, decisions, sign-offs and drafts in the folder `.app-state` of the repository when it is started with `make serve`, so a restart shows them again, and deleting the folder starts afresh. When it is started with the seed it makes two briefs on first start, both runs of the whole of the fictional policy statement PS26/4 for the fictional Harbour Mutual Bank, read by the real workflow from the saved model calls: one waiting for a reviewer, which you work through, and one already signed by Dana Whitfield, Head of Compliance, a fictional reviewer. Where this guide names a count for one of those two briefs, the page shows the same; for a brief you start yourself, the page shows its own. Where it names a fact, pick it by the paragraph it cites, such as "Paragraph 7.1, obligation". Facts about the firm and its providers are named in words, for example "Harbour Mutual Bank, firm profile: total assets".

## Start the application

1. Set the repository up as the README's Setup describes, then run this from the repository root:

   ```bash
   APP_SEED=compliance-brief APP_HOST=127.0.0.1 APP_PORT=4821 make serve
   ```

   Add `PYTHON=/path/to/python` when you did not use `uv sync`. It prints `Uvicorn running on http://127.0.0.1:4821 (Press CTRL+C to quit)`. Open the address it prints in a browser. If it refuses to start and names a folder, the folder holds briefs made from other recordings or by a start that stopped partway; delete the folder it names and start again. Stop the application with Ctrl+C.
2. The home page leads with what waits for a reviewer, in a sentence such as "1 brief is waiting for a reviewer." Under it is one tile for each workflow that is built, headed by the workflow's name and giving how many items of it are waiting; a tile opens that workflow's list.
3. Look at the bar along the top. It holds "Review desk", "Compliance brief", "Demo", "About" and "Sign in". The word "Demo" marks that the data is fictional.
4. Click "About". The sentence reads "This is a demonstration on fictional data from the hackathon starter." The page says what the data is and how a brief is made, and it ends with the product's statement about the status of its output.

## Sign in

5. Click "Sign in". The sentence reads "Sign in with your name and role to decide on a brief."
6. Type `Dana Whitfield` in "Your name" and `Head of Compliance` in "Your role", then click "Sign in". The top bar now shows "Dana Whitfield, Head of Compliance" and a "Sign out" button. Any name and role of a person will do; the application records what you type.
7. To see the refusal, click "Sign out", click "Sign in" and type `Claude` as the name and `Assistant` as the role. The page stays on the form and says "The name 'Claude' is a model, a program or a service; only a person may decide." Sign in again as Dana Whitfield.

## Open the waiting brief

8. Click "Compliance brief" in the top bar, or the tile of that name on the home page. The sentence counts the briefs and says how many wait for a reviewer and how many are signed, here "2 briefs so far: 1 waiting for a reviewer, 1 signed.", and the three tiles read "Briefs", "Waiting for a reviewer" and "Signed". The list names each brief, for example "PS26-4 for Harbour Mutual Bank", with its Sections ("All" when the whole document was read), its Status and who reviewed it ("Not yet" for a brief no one has signed or returned, otherwise the reviewer's name, role and the date).
9. Click the brief whose Status is "Waiting for a reviewer". The review page opens.

## Read the answer

10. The review page's sentence reads "The brief for Harbour Mutual Bank has 50 statements resting on 57 facts. 57 facts and 4 questions still need your decision before it can be signed." Under it are three tiles. "Statements" counts the statements. "Facts decided" shows how many of the facts the brief cites are decided, as "0 of 57", with the badge "Needs a person". "Questions settled" shows "0 of 4", with the same badge.
11. Below the tiles are tabs: "Brief", "Firm profile", "Open questions", "Facts" and "Sign-off". The "Brief" tab is open. Across the top of it is a picture of the document: one small box for each of the 48 paragraphs, in the document's order under the heading of its section, with the paragraph's number and a mark for what was found in it. The whole picture is in view with no scrolling at 1366 by 768, and on a phone it wraps to the width of the window. A line above it reads "48 of 48 paragraphs of the document accounted for", and a key beside that line names the marks the picture uses, which depend on the brief: on this waiting brief it reads "Open question", "Obligation" and "No fact", and it would add "Other fact", "Question settled" and "Failed check" for a brief that has them. Hover over a box to read what was found in the paragraph. Four boxes carry the mark "Open question", for paragraphs 6.6, 7.4, 9.1 and 9.4, and show in amber with an icon; a box that failed a check would carry "Failed check" in coral. Under the picture, on the left, are the statements. What the document requires comes first: each statement sits under a heading the run chose, and under it are the facts it cites, for example "Paragraph 7.1, obligation", each with the badge "Needs a person". The statements about the firm come last, and each carries one badge, "Firm profile", with the state of the whole profile; the badge opens the "Firm profile" tab.

## Open a source

12. Click a paragraph box in the picture, such as "7.1". The source panel on the right changes to "Paragraph 7.1" and the policy statement's title, and shows the paragraph: "Firms must submit an initial notification to the FSOA within 4 hours of classifying an incident as a major incident, and in any case no later than 24 hours after the incident is first detected." The words the fact quotes are marked with a dark underline on a grey fill. A line "Document digest" gives the digest of the document. The decision form sits under the paragraph, so the reason box and the button are in view without scrolling the panel. Click a box that carries the mark "No fact", such as "1.1": the panel shows the paragraph's text and says "No obligation was found in this paragraph."
13. Click a fact under a statement, such as "Paragraph 7.1, obligation". Read the fields under the decision form. "Deadline as written" and "Requirement" hold what the fact says. "Known as" reads "Stated in the document". "Checks" lists "Passed The quote is word for word in the paragraph" and "Passed The deadline is word for word in the paragraph". If a check had failed, the entry would show the badge "Failed" and the brief would not cite the fact.

## Decide the firm profile

14. Click the "Firm profile" tab. The block "The firm profile the brief was written against" lists, in words, what the brief states about the firm and then about each provider: the firm's name, type, customers and total assets, a field the firm table leaves empty as "none named", and each provider by its name with its service and contract. Each row gives the field and its value, and under them the row's badge and its "Source" link, so both are in view at any window width. Click a "Source" link: the row opens on the right as a table of field and value, with the quoted field marked.
15. Below the block is one decision form for the whole profile. Choose "Accept", type `The firm and provider tables say this.` in "Your reason" and click "Record my decision about the profile". Every row now shows "Accepted by you", the block says "Accepted by you, on" the day's date, "covering 12 facts", with your reason, and the tile "Facts decided" reads "12 of 57". The firm and provider facts are not decided one by one. Choosing "Amend" shows the box "Amended profile, in your words"; leaving it empty is refused with "Write the amended wording in your own words." The page then opens the first paragraph fact that still needs a decision.

## Accept a fact

16. In the panel's "Your decision" group, choose "Accept". In "Your reason" type `The paragraph says this in these words.` and click "Record my decision". If you leave "Your reason" empty, the browser asks you to fill it in.
17. The panel moves to the first fact that still needs a decision. The sentence now says one fewer fact still needs your decision, and the fact you decided shows the badge "Accepted by you" beside its statement.

## Amend a fact

18. Click "Paragraph 7.2, obligation". Choose "Amend"; the box "Amended wording, if you amend" appears. Type `Submit an intermediate report within 72 hours of the initial notification, with the cause, the services and customers affected and the actions taken.` In "Your reason" type `The cause needs the firm's wording.` and click "Record my decision". The fact shows "Amended by you". Choosing "Amend" and leaving the wording empty is refused: the page stays on that fact and says "Write the amended wording in your own words." beside the form, with your reason kept.

## Reject a fact

19. Click a fact named "Paragraph 7.3, obligation"; two carry that name, so take the first. Choose "Reject", type `The deadline needs checking with the regulator.` as the reason and click "Record my decision". The fact shows "Rejected by you".
20. Decide every paragraph fact still marked "Needs a person". For each, choose "Accept", type `Matches the source.` and click "Record my decision"; the panel opens the first fact still waiting each time, and the sentence counts the facts down. When the last is recorded the tile "Facts decided" reads "57 of 57" and the sentence speaks of the questions: "4 questions still need your decision before it can be signed." Open the "Sign-off" tab: the button "Sign the brief" is greyed out, and the message above the form reads "The brief cannot be signed yet: 4 questions not answered or accepted."

## Settle the open questions

21. Click the "Open questions" tab. It holds one block for each of the four questions, for paragraphs 7.4, 6.6, 9.1 and 9.4. A block opens with what was found, for example "An obligation was read from paragraph 9.1 of PS26-4, which holds none of the words that mark an obligation. The quote is" the paragraph's own words, then the question "Does paragraph 9.1 place an obligation on the firm?" with the badge "Needs a person". Under it are whom to ask and the priority, then "Why it is not known", which says the paragraph has none of the words that usually mark a duty and that the obligation rests on how the paragraph was understood and not on its wording, "What changes with the answer" and "Rests on", with a link to each fact the question rests on. The question about paragraph 9.4 rests on two facts and quotes both. On a phone each label sits above its text. Each of the four is about a paragraph from which an obligation was read although it holds none of the words that mark one, and a person says whether it places one on the firm.
22. Answer the question about paragraph 9.1. In "Your answer" type `No. Paragraph 9.1 places no obligation on the firm. It lets small firms meet four requirements by 31 March 2028 instead of 31 March 2027.` In "What your answer rests on" type `The paragraph says may and gives a later date.` and click "Record my answer". The block shows "Answered by you" with your answer, the day it was given and what it rests on. The box for paragraph 9.1 in the picture on the "Brief" tab now carries "Question settled", in grey with a tick, in place of amber. The tile "Questions settled" reads "1 of 4". Leaving either box empty is refused, for example with "Write the answer in your own words.", and the form keeps what you typed in the other box.
23. Accept the question about paragraph 7.4 as an assumption. In "Or accept it as an assumption, in your words" type `I am treating paragraph 7.4 as an obligation on the firm.` and click "Accept as an assumption". The block shows "Accepted by you as an assumption" with your words under "Your assumption", and the tile reads "2 of 4". An assumption goes into the sign-off record as an assumption, in your words, and is never recorded as an answer.
24. Answer the questions about paragraphs 6.6 and 9.4 as you did in step 22, in your own words. The tile reads "4 of 4" and the sentence now reads "You rejected 1 fact, so the brief can be returned but not signed." Open the "Sign-off" tab: "Sign the brief" is still greyed out, and the message above the form reads "You rejected 1 fact that the brief cites. Return the brief so that it can be written again." The button "Return the brief" is available.

## Change a decision

25. Click the "Brief" tab and click the fact you rejected. The decision group is now headed "Change your decision", and above it the page says "Your decision: Rejected by Dana Whitfield, Head of Compliance, on" followed by the day's date and your reason.
26. Choose "Accept", type `Checked: the paragraph gives 30 business days.` and click "Record my decision". The sentence now ends "Every fact and question is settled, so it is ready for you to sign."

## Read the facts table

27. Click the "Facts" tab. The sentence reads "57 facts support the brief for Harbour Mutual Bank; every one has a decision." The tiles read "Facts", "Decided" and "Failed checks"; "Decided" shows the same number on both sides of "of" and "Failed checks" shows 0. The picture of the document leads the page, with the four boxes for paragraphs 6.6, 7.4, 9.1 and 9.4 carrying "Question settled" and none in amber, and the table is below it, with the columns "Source", "Kind", "Requirement", "Deadline as written", "Checks" and "Decision". Click a column heading to sort by it, click a source to open it on the review page, and click "Export CSV" to download the rows as `facts.csv`.

## Sign the brief

28. Click the "Sign-off" tab. The text "You are acting as Dana Whitfield, Head of Compliance." shows who signs, and "Sign the brief" is now available. Leave "Why you are returning the brief, if you return it" empty and click "Sign the brief".
29. The sign-off record opens, under a tab of that name. The sentence reads "Dana Whitfield, Head of Compliance, signed the brief for Harbour Mutual Bank." The tiles read "Statements", "Decisions recorded" and "Assumptions accepted". "Statements" counts the statements of the brief you read, "Decisions recorded" counts the decisions the table below lists, and "Assumptions accepted" is 1, the one you accepted in step 23.

## Read the sign-off record

30. The page reads in this order. First the sentence. Then the brief as it was signed: each statement with the facts it cites and the decision each fact stands on. Click a fact there, or a paragraph box in the facts table's picture, to read its source beside the statements, with the decision and the reason that settled it. The page offers no form, so nothing on a signed brief can be changed. Then the sign-off record: "Reviewer" is Dana Whitfield, "Role" is Head of Compliance, "Date" is the day's date in the form 25 November 2026, "Outcome" is Signed, and "Digest signed" shows the start of the digest of the brief you read; hover over it, or tab to it and press Enter, to read the whole value. Under it the assumption you accepted shows as "Accepted as an assumption" with your words. Last, the table "Decisions made on the brief" has one row for each decision, with "About", "Requirement", "Decision", "Reviewer", "Date" and "Reason". The firm profile is one row, "Firm profile" with the number of facts it covered and their names, because you decided it once. The amended fact shows "Amended:" and your wording, and each question answered has its own row, shown as "Answered:" with the answer. Click "Export CSV" to download the table as `decisions.csv`.
31. Click "Compliance brief" in the top bar. The list now shows both briefs with Status "Signed" and tells them apart by the reviewer and the date in the last column. The sentence counts them, here "2 briefs so far: 2 signed." "Export CSV" above the list downloads it as `briefs.csv`. Open the brief that was already signed when you started: its record reads the same way, with the seeded reviewer's own words as the reasons and answers.

## Start a brief of your own

32. Find the panel "Start a brief". "Document" shows PS26-4 and "Firm" shows Harbour Mutual Bank. All ten boxes under "Sections to read" are ticked; leave them ticked. With `MODEL_BACKEND` at its default of `replay`, the application can only start a brief that has saved calls, which is the whole document. A brief on part of it stops with the reason "No saved answer is held for part of this brief, so it could not be written here." To start any sections, set `MODEL_BACKEND=claude-code` in `.env` and restart: each section is then read by headless Claude Code on your signed-in account, which takes a few minutes for the whole document, four calls at a time.
33. Click "Start the brief". On the saved calls the brief is ready within a few seconds: you may see the page that says the brief is being written, with every section "Waiting", for about three seconds before the review page opens by itself. A run read live on Claude Code shows a page that says the brief is being written, "The brief for Harbour Mutual Bank is being written: 0 of 10 sections read." at first, with a table of the sections and whether each is read, and refreshes itself every 3 seconds; the table shows each section as "Waiting" or "Read". Starting a second brief while one is still being written is refused in words (see the last part of this guide). When the brief is ready the review page opens.

## A second run with decisions carried

34. Decisions are carried from every brief already signed on this firm and document, and that includes the brief that was already signed when you started, so some of the decisions carried here may be the seeded reviewer's and not yours. On the saved calls this brief holds the same facts, word for word, as the one you signed, so the sentence asks for no fact decision, the tile "Facts decided" shows the same number on both sides of "of", and each fact beside its statement shows "Carried: accepted", or "Carried: amended" for one that was amended, with the date of that decision. On the "Open questions" tab each of the three questions answered before, by you or by the seeded reviewer, shows the badge "Answered by" with who answered, and under it "Answer" with the words given, "Given by" with the name, role and date, and "What it rests on" with the reason. Signed in as the person who answered, the badge reads "Answered by you". In the picture on the "Brief" tab their boxes carry "Question settled". The tile "Questions settled" reads "3 of 4": the question about paragraph 7.4 waits, because an assumption belongs to the brief it was accepted on and is never carried.
35. Hover over a "Carried" badge to read who decided and on what date, then "Nothing judged has changed since." Click a carried fact: the panel says who decided and when, then "Reason given:" with the reason that person gave, which may not be the one you typed. On the saved calls every fact is worded as it was in the first run, so none is asked again and "Since then these changed:" does not appear. A run read live on Claude Code words some facts differently, and a fact worded differently, for example a requirement put another way, is asked again. It shows "Needs a person", and its panel shows your earlier decision, who made it, when and why, then "Since then these changed:" with the part that changed, such as "Requirement". Decide it again. This is the design: a decision is carried only while the fact's judged content is unchanged. The "Firm profile" tab shows the same: the profile is settled when every fact in it is.
36. Click "Sign out" in the top bar, then reload the review page. It still shows the brief and its carried decisions, and in place of the decision forms it says "Sign in to decide on this fact." Nobody can decide without signing in by name and role. Sign in again as Dana Whitfield.

## Return a brief

37. On the new brief click the "Sign-off" tab. Leave "Why you are returning the brief, if you return it" empty and click "Return the brief". The page says "Write why you are returning the brief in your own words." once, and records nothing. A brief can be returned whether or not every fact has a decision.
38. Type `The brief needs the root cause paragraph read again.` in that field and click "Return the brief". The sentence reads "Dana Whitfield, Head of Compliance, returned the brief for Harbour Mutual Bank." and the record shows "Outcome" Returned, "Digest returned" and "Reason for returning". Above the table of decisions a line says how many of them were carried from an earlier review, here every one, because you made none on this brief, and each reads "carried from an earlier review". The firm profile is still one row. The list at "Compliance brief" now counts the returned brief.

## What each page's sentence means

Each page opens with one sentence that answers the question the page is for, and the tiles under it count the same things.

| Page | Question it answers | Sentence |
| --- | --- | --- |
| Home | What waits for a reviewer? | "1 brief is waiting for a reviewer." or, with several workflows, each workflow's count in one sentence |
| About | What is this? | "This is a demonstration on fictional data from the hackathon starter." |
| Sign in | Who is deciding? | "Sign in with your name and role to decide on a brief." |
| Compliance brief | What is ready to brief and what waits for a person? | "3 briefs so far: 1 waiting for a reviewer, 1 signed, 1 returned." The words are "waiting for a reviewer", "being written", "signed", "returned" and "stopped". |
| A brief being written | How far has the brief got? | "The brief for Harbour Mutual Bank is being written: 1 of 10 sections read." |
| A brief that stopped | Why did it stop? | "The brief for Harbour Mutual Bank stopped before it was finished." with the reason under it |
| Review | What needs my decision before I can sign? | "The brief for Harbour Mutual Bank has" its statements and facts, followed by what still needs a decision, or "Every fact and question is settled, so it is ready for you to sign.", or "You rejected 1 fact, so the brief can be returned but not signed." |
| Facts | Which facts does the brief rest on and where do they stand? | "These facts support the brief for Harbour Mutual Bank; every one has a decision." or, with some undecided, the same sentence ending "5 still need a decision." |
| Sign-off record | Who signed, when, and what did they decide? | "Dana Whitfield, Head of Compliance, signed the brief for Harbour Mutual Bank." or "returned" in place of "signed" |

## When something fails

| What you see | What it means and what to do |
| --- | --- |
| The page does not load | Check the address against the one `make serve` printed, and that the command is still running. |
| "There is nothing at this address." | The address has no page. Click "Go to the home page". |
| "There is no run" followed by a number | The state folder was deleted, or the application was started without `APP_STATE_DIR`, which keeps everything in memory and forgets it at a restart. Start the brief again. |
| "Sign in with your name and role to start a brief." | You are not signed in. Click the sentence, which is a link to the sign-in page. |
| "Choose at least one section." | Tick a section in the start form. |
| "A brief is still being written. Start another when it has finished." | One run is written at a time. On the saved calls a run ends at once, so you meet this only on a live run. Wait for the review page to open for the first, then start the next. |
| "The brief for Harbour Mutual Bank stopped before it was finished." with the reason "No saved answer is held for part of this brief, so it could not be written here." | The sections you ticked have no saved calls. Start the brief again with all ten ticked, or set `MODEL_BACKEND=claude-code` as step 32 describes. |
| "The brief for Harbour Mutual Bank stopped before it was finished." with another reason | A model call failed or the run could not finish. Click "Back to the briefs" and start the brief again. |
| "Write your reason in your own words." | The reason is empty. Write it and record the decision again. |
| "Write the amended wording in your own words." | You chose "Amend" and left the wording empty. The page stays on that fact; write the wording, or choose another outcome, and record the decision again. |
| "Write the answer in your own words." or "Write the assumption in your own words." | The answer or the assumption is empty. Write it and record it again. |
| "The brief changed after you opened it, so nothing was recorded. Read it again; decisions you made on facts that did not change are kept." | The brief you were reading is no longer the current one, for example because it was open in two windows. Reload the review page and decide again. |
| "The brief was not recorded as signed." or "The brief was not recorded as returned." followed by a reason | The server refused the sign-off after you sent it and the brief stays at the review, with what you typed kept. Tell the person who runs the server, giving the reason shown. |
| "Sign the brief" is greyed out | Read the message above the form. It says how many facts have no decision or how many questions are not answered, or that you rejected a fact. |
| "Decisions on this brief were made by" followed by a name | Someone else's decisions are held on this brief. Sign in as that person to sign it, or record your own decisions again. You meet this only after two people have decided on one brief, which the seeded application does not set up, so it does not appear on a first walk. |
