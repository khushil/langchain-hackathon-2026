# How the KYC onboarding agent is measured

This folder holds the dataset, the scoring code and the planted faults for topic 01. Everything here scores one thing: what the engine proposes for each of the starter's 25 fictional account applications, set against the starter's own labels.

The labels are the starter's, and this repository did not make them. They are the 25 entries of `LABELS` in the starter's `scripts/run_experiments.py`, lines 51 to 77, at commit `12acee0`, carried unchanged into `data/starter_labels.tsv` with their source named at the top of the file. Each has a risk level, high or low, and a reason. The expected decision is derived as the starter derives it: reject for high and approve for low. Three reasons begin "Edge case", and the starter marks those three customers as edge cases.

No scoring code calls a model, and none imports from the engine. `engine_outputs.py` is the one module that runs the engine, up to the point where a person takes over, and hands each application's result to the scoring as plain JSON.

## What is scored

The unit is one application's result: the proposed risk level and decision, whether the checks settled it, the name and date of birth the reading gave, and how many of the application's units were accounted for. Each measure is a count over a stated population. A denominator of zero is reported as "none in scope", never as 0 or 100 per cent, and a run that scores nothing is reported as a failure.

| Measure | What it counts |
| --- | --- |
| `risk_agrees` | Applications whose proposed risk level is the label's |
| `decision_agrees` | Applications whose proposed decision is the label's expected decision |
| `settled_by_checks` | Applications the checks settled |
| `sent_to_person` | Applications the checks did not settle, which go to a person with a question |
| `settled_agree` | Settled applications whose risk level and decision both agree with the label, of the settled applications |
| `edge_cases_sent` | Edge cases that were sent to a person, of the three the starter's labels mark |
| `starter_risk_agrees` | Applications where the starter's own rule gives the label's risk level |
| `starter_decision_agrees` | Applications where the starter's own rule gives the label's expected decision |
| `applications_accounted` | Applications that ended with a fact or a reason, of the applications read |
| `screenings_accounted` | Pairings of an application with a list entry that ended with a fact or a reason, of all pairings |

The starter's own rule is the starter's screening applied to the name and date of birth the engine read: any watchlist hit makes the customer high risk, and the starter's evaluation then rejects every high-risk case and approves the rest. It is scored beside the engine on the same labels.

An engine that holds an application for a person when the label says low risk does not agree with the label on risk level. That is the cautious reading, and the table shows it as a miss on the first two measures and a hit on `edge_cases_sent`. The three edge cases are what the method is for, so no rule is written for them and the measures do not excuse them.

## The files

| File | What it does |
| --- | --- |
| `data/starter_labels.tsv` | The starter's labels, carried unchanged, never edited |
| `data/examples.jsonl` | One example for each application: the label, the expected decision, the application's text and whether it is an edge case |
| `data/baseline_profiles.tsv` | The name and date of birth each application states, which the planted faults start from |
| `labels.py` | Reads the labels and checks that they name the applications and no others |
| `build_dataset.py` | Builds the examples from the labels and the applications; `--check` fails if the file is out of date or the labels' digest is not the one on record |
| `engine_outputs.py` | Runs the engine to the review and reads each application's result |
| `evaluators.py` | The ten measures as plain functions and as LangSmith evaluators |
| `planted_faults.py` | Puts one fault at a time into outputs built from the labels and checks that the right measures move |
| `upload.py` | Uploads the dataset to LangSmith, once |

## The planted faults

A check that has never failed proves nothing, so each measure has a fault that it must catch. Every fault starts from outputs built from the labels themselves, where each application agrees with its label, the edge cases are held for a person and the rest are settled by the checks, and changes one thing. `python -m evals.planted_faults`, run from the topic folder, prints one line per fault, CAUGHT or MISSED, and exits non-zero if any is missed. A fault is caught only when the measures that move are the ones named for it and no others.

| Fault | What is changed | Measures that move |
| --- | --- | --- |
| Wrong risk on a held application | An application held for a person is given the wrong risk level | `risk_agrees` |
| Wrong decision on a held application | An application held for a person is given the wrong decision | `decision_agrees` |
| Wrong settled proposal | A settled application is given the wrong risk level | `risk_agrees`, `settled_agree` |
| Edge case settled by the checks | An edge case is settled instead of sent | `edge_cases_sent`, `sent_to_person`, `settled_agree`, `settled_by_checks` |
| Starter's rule blinded | The reading gives no name for an application the starter's rule would catch | `starter_risk_agrees`, `starter_decision_agrees` |
| Screening dropped | One pairing is not accounted for | `screenings_accounted` |
| Application dropped | One application is not accounted for | `applications_accounted` |

## Running the checks

From `01_kyc_agent`, with the shared member on the path:

```bash
export PYTHONPATH=../fsi_common
python -m evals.build_dataset --check
python -m evals.planted_faults
```

`python -m evals.upload` puts the dataset in LangSmith once, as `kyc-onboarding-starter-labels` with 25 examples; a second run adds nothing, and a run with changed content is refused.

The starter's own experiment script is carried at `scripts/run_experiments.py`. It builds its own dataset from the same labels and runs the starter's graph with its six evaluators. It needs a traced run and a LangSmith project, and it is not part of the checks above.
