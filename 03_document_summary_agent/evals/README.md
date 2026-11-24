# How the compliance brief is measured

This folder holds the dataset, the scoring code and the planted faults for topic 03. Everything here scores one thing: the list of obligations that a section's sub-agent returns for a section of the fictional policy statement PS26-4, set against the reference labels for that section. The starter's own agent and this repository's engine return the same shape, so the same code scores both and the numbers can be set side by side.

No scoring code calls a model, and none imports from the engine. A scorer that shared code with the system it scores would share its mistakes.

## The reference labels

`data/reference_labels.tsv` has 77 rows over all 48 paragraphs of PS26-4. It holds 39 obligations in 23 paragraphs, 16 of them with a deadline.

Two independent labelling agents each read every paragraph, working to written rules fixed before either started. The rules follow the starter's own definition of an obligation: a requirement on the firm marked by "must", "shall", "is required to" or "will need to", with "should", "may" and statements of what only the regulator does left out. The two sets agreed on which 23 paragraphs hold an obligation, and differed in 8 of the 48 paragraphs: on how finely to split a paragraph into rows, on one deadline and on whether one obligation applies to the firm. The coordinating session settled each difference under the rules and recorded the reason. The adjudicated file is the one used here, and its SHA-256 is checked on every build.

Both labelling agents are the same model, so their agreement shows how consistently one model reads the rules and says nothing about how a person would read them.

## What is scored

The unit is one section's summary as JSON: its `number`, `title`, `summary` and `obligations`, each obligation with `requirement`, `paragraph`, `deadline` and `evidence`. The document-level score adds the ten sections together. The measures were fixed before any run, and a change to a measure after a result has been seen would make the evidence circular, so none is made.

### Comparing text

Before any two strings are compared, both are put in one form: Unicode NFC, curly quotes and apostrophes straightened, every run of spaces and line breaks collapsed to one space, the ends trimmed and one trailing full stop removed. Capital letters are kept, so a changed capital is a changed wording.

A string is word for word in a paragraph when its normalised form is a contiguous part of the normalised paragraph text, taken from the paragraph's line in PS26-4 without its number. An empty string is never word for word.

### Matching a predicted obligation to a labelled one

A predicted obligation matches a labelled obligation when both cite the same paragraph and either the normalised evidence of one contains the evidence of the other, or the lower-cased words of the two pieces of evidence have a Jaccard index of at least 0.5. Pairs are made one to one, the highest Jaccard index first, with ties broken by the order of the labelled items. Paragraph 8.5 has two labelled obligations with the same evidence, so the tie rule decides which predicted obligation takes which.

### The seven measures

Each measure reports a numerator, a denominator and the population the denominator counts. A denominator of zero is reported as "none in scope", never as 0 or 100 per cent, and a run that scores nothing at all is reported as a failure.

| Measure | What it counts | Example |
| --- | --- | --- |
| `obligations_found` | Labelled obligations that a predicted obligation matched, of the labelled obligations in scope (39 for the document) | A summary of section 7 that returns the initial notification, the intermediate report and the final report but not the root-cause analysis scores 3 of 4 |
| `invented_obligations` | Predicted obligations that match no labelled obligation and cite a paragraph holding no labelled obligation, or a paragraph that does not exist, of all predicted obligations (lower is better) | An obligation to publish a template, cited to paragraph 7.5, where only the regulator acts, scores 1 of 5 |
| `quotes_word_for_word` | Predicted obligations whose evidence is word for word in the cited paragraph, of the predicted obligations citing a paragraph that exists | Evidence that changes "must" to "shall" is not word for word |
| `deadlines_as_written` | Predicted obligations with a deadline that is word for word in the cited paragraph, of the predicted obligations that give a deadline | "within four hours" for paragraph 7.1, which says "within 4 hours", fails |
| `deadlines_matched` | Matched pairs where the predicted deadline contains the labelled deadline or sits inside it, of the matched pairs whose labelled deadline is not empty | A matched obligation with no deadline, where the labelled one has "by 31 March 2027", fails |
| `paragraph_recall` | Paragraphs holding a labelled obligation that also hold a predicted one, of the paragraphs holding a labelled obligation (23 for the document) | A summary that finds nothing in 7.2 scores 2 of 3 for section 7 |
| `paragraph_precision` | Paragraphs holding a predicted obligation that also hold a labelled one, of the paragraphs holding a predicted obligation | An obligation cited to 7.5 makes 7.5 a wrong paragraph |

A deadline that is word for word in its paragraph is never counted against the summary when the labelled item has none. Paragraph 6.3 says the provider must report incidents "without undue delay", and the labels give the firm's duty no deadline of its own; a summary that quotes the phrase is not penalised for it.

For a section, the paragraphs in scope are that section's own. A predicted obligation that cites a paragraph of another section is treated as citing a paragraph outside the section, so it can be invented but never matched.

Sections 1, 3 and 10 hold no labelled obligation, so their obligation measures report "none in scope" for them and add nothing to the document total.

## The files

| File | What it does |
| --- | --- |
| `data/reference_labels.tsv` | The adjudicated labels, never edited |
| `data/sections.jsonl` | One example per section of PS26-4, ten lines in section order |
| `data/documents.jsonl` | One example for PS26-4 and Harbour Mutual Bank, with every labelled item |
| `build_dataset.py` | Builds the two files from the labels and the document; `--check` fails if they are out of date or the labels are unsound |
| `labels.py` | Reads the labels and checks them against the document |
| `reference_summary.py` | Builds a summary from the labels, and scores it as a check on the scorers |
| `evaluators.py` | The seven measures as plain functions and as LangSmith evaluators |
| `matching.py`, `normalise.py` | The pairing rule and the text rules the measures share |
| `planted_faults.py` | Puts one fault at a time into a summary built from the labels and checks that the right measures fall |
| `upload.py` | Uploads the two datasets to LangSmith, once |

`build_dataset.py --check` fails when the labels do not cover 48 of 48 paragraphs, when a labelled quote or deadline is not word for word in its paragraph, when the labels' digest is not the one on record, or when a file on disk differs from what the build produces.

## The planted faults

A check that has never failed proves nothing, so each measure has a fault that it must catch. Every fault starts from the summary built from the labels themselves, which scores in full on every measure, and changes one thing. `python -m evals.planted_faults`, run from the topic folder, prints one line per fault, CAUGHT or MISSED, and exits non-zero if any is missed. A fault is caught only when the measures that fall are the ones named for it and every other measure stays at its full score.

| Fault | What is changed | Measures that fall |
| --- | --- | --- |
| Paraphrased quote | One word of the evidence in paragraph 7.1 is replaced by a near synonym | `quotes_word_for_word` |
| Converted deadline | "within 4 hours" in paragraph 7.1 is written "within four hours" | `deadlines_as_written`, and `deadlines_matched`, because a converted deadline is also no longer the labelled one |
| Invented obligation | An obligation is added for paragraph 7.5 | `invented_obligations`, and `paragraph_precision`, because 7.5 becomes a wrong paragraph |
| Dropped obligation | One of two obligations in paragraph 7.3 is left out of the document | `obligations_found` |
| Dropped deadline | The deadline of the obligation in paragraph 7.2 is left out | `deadlines_matched` |
| Lost paragraph | The only obligation in paragraph 7.2 is left out | `obligations_found`, and `paragraph_recall` |

## Running the checks

From `03_document_summary_agent`, with the shared member on the path:

```bash
export PYTHONPATH=../fsi_common
python -m evals.build_dataset --check
python -m evals.planted_faults
python -m evals.reference_summary
```

The last command scores the summaries built from the labels and must show every measure in full. `python -m evals.upload` puts the two datasets in LangSmith once, as `compliance-brief-ps26-4-sections` with ten examples and `compliance-brief-ps26-4-document` with one; a second run adds nothing, and a run with changed content is refused.
