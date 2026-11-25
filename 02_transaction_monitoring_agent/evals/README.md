# How transaction monitoring is measured

This folder holds the dataset, the scoring code and the planted faults for topic 02. Everything here scores one thing: the proposals an assessor records for a customer's card transactions, set against the starter's own reference data. The starter's agent and this repository's workflow keep the same record for each transaction, so the same code scores both and the numbers can be set side by side.

No scoring code calls a model, and none imports from the workflow. A scorer that shared code with the system it scores would share its mistakes.

## The reference data

The starter ships three files, and nothing is added to them:

| File | What it holds | How it is used |
| --- | --- | --- |
| `data/analyst_labels.jsonl` | The analysts' decision, risk score and whether a person was warranted, for eleven transactions before 19 October | The reference of the first two examples |
| `data/reviewer_answers.jsonl` | The two replies the starter's scripted reviewer gives when the agent asks | Part of the inputs of the examples that hold the transactions they are about |
| `data/simulated_annotations.jsonl` | The score a reviewer gives, and a comment, for each of the four transactions of the week after | The reference of the third example, labelled by the starter's own rule: block from 70, ambiguous from 30 to 69 |

`build_dataset.py` reads them and checks them against the starter's own rule. In every one of the eleven rows the analysts' decision is a block when the score is 70 or more and not otherwise, and the label is ambiguous when the score is from 30 to 69 and not otherwise. The build refuses a label for a transaction the data lacks, a label that breaks the rule, a transaction with neither a label nor a review, and a scripted reply for a transaction the analysts did not call ambiguous. It reports each count: labels used of labels in the file, reviews used of reviews, replies used of replies, and transactions in an example of all the transactions.

The labels were written by the starter's authors for the starter's data. They are the reference for the measures here, and they say nothing about any other data.

## The examples

`data/examples.jsonl` holds three examples. Each has a key, the inputs and the reference:

| Key | Inputs | Reference |
| --- | --- | --- |
| `USR-001/before-19-october` | The customer, the window before 19 October, the six transactions and the scripted replies | The analysts' labels of the six transactions |
| `USR-002/before-19-october` | The same for the second customer's five transactions | The analysts' labels of the five |
| `USR-001/from-19-october` | The window from 19 October and the four transactions of the week after | The labels the four simulated reviews give by the starter's rule |

## What is scored

An assessment is a transaction id, the risk score the assessor gave, the decision it proposed and its confidence. For the starter's agent they are read from its decision log, taking the agent's own decision and not the final one, because a person decides the final one. For the workflow they are read from the records the assessing step kept, so a proposal that failed a check is scored as the assessor gave it.

Each measure reports a numerator, a denominator and the population the denominator counts. A denominator of zero is reported as "none in scope", never as 0 or 100 per cent, and a run that scores nothing at all is reported as a failure. The thresholds are the starter's: a transaction is flagged for a person when its confidence is below 0.7, which is the confidence below which the starter's agent asks, and a score is in band when it lies within 20 points of the analysts', which is how near the starter's own judge treats a reviewer's score as agreeing.

| Measure | What it counts | Population |
| --- | --- | --- |
| `assessed` | Labelled transactions with an assessment | Labelled transactions |
| `decisions_agree` | Labelled transactions whose proposed decision is the analysts' | Labelled transactions |
| `blocks_found` | Labelled blocks proposed as a block | Labelled blocks |
| `false_blocks` | Labelled approvals proposed as a block (lower is better) | Labelled approvals |
| `scores_in_band` | Labelled transactions whose score is a whole number within 20 points of the analysts' | Labelled transactions |
| `ambiguous_flagged` | Labelled ambiguous transactions that are flagged for a person | Labelled ambiguous transactions |
| `clear_not_flagged` | Labelled clear transactions that are not flagged | Labelled clear transactions |

A transaction the assessor never assessed misses every measure it is in the population of, except `false_blocks`, where an assessment that does not exist is not a block. An assessment for a transaction nobody labelled is not counted.

## The files

| File | What it does |
| --- | --- |
| `data/examples.jsonl` | The three examples, never edited by hand |
| `build_dataset.py` | Builds the file from the starter's three reference files; `--check` fails if the file is out of date or a reference file breaks the starter's rule |
| `evaluators.py` | The seven measures as plain functions and as LangSmith evaluators, and the readers of the starter's decision log and of a run's records |
| `reference_assessments.py` | Builds the assessments an assessor that agreed with the analysts would record |
| `planted_faults.py` | Puts one fault at a time into those assessments and checks that the right measures fall |
| `upload.py` | Uploads the dataset to LangSmith, once |
| `scoring_evals.py` | The starter's own three evaluators, carried as they are and run in the notebooks on our model |

## The planted faults

A check that has never failed proves nothing, so each measure has a fault that it must catch. Every fault starts from the assessments built from the labels themselves, which score in full on every measure, and changes one thing. `python -m evals.planted_faults`, run from the topic folder, prints one line per fault, CAUGHT or MISSED, and exits non-zero if any is missed. A fault is caught only when the measures that fall are the ones named for it and every other measure stays at its full score.

| Fault | What is changed | Measures that fall |
| --- | --- | --- |
| Approved a block | The Singapore jewellery, which the analysts block, is proposed as an approval | `blocks_found`, `decisions_agree` |
| Blocked an approval | A small grocery shop is proposed as a block | `decisions_agree`, `false_blocks` |
| Score far off | The gift cards are scored 72 where the analysts score 95, still a block | `scores_in_band` |
| Ambiguous not flagged | The hotel in Lisbon is recorded with a confidence of 0.9 | `ambiguous_flagged` |
| Clear flagged | A small grocery shop is recorded with a confidence of 0.5 | `clear_not_flagged` |
| Dropped assessment | The coffee in Lisbon is never assessed | `assessed`, `clear_not_flagged`, `decisions_agree`, `scores_in_band` |

## The dataset in LangSmith

`python -m evals.upload`, run from the topic folder with a LangSmith key in the environment, creates the dataset `transaction-monitoring-reference` from `data/examples.jsonl`. It checks the file against the starter's files first, and it never changes a dataset on a rerun: a dataset of that name with the same content is left as it is, and one with different content is refused.
