# Transaction monitoring

In the FSI hackathon starter this topic builds a fraud-monitoring agent over a stream of card transactions. It
remembers earlier transactions and what reviewers have said about each customer, scores every transaction, and
pauses for a person when it is not confident. Its evaluations compare the agent's decisions, risk scores and
review routing with analysts' labels in LangSmith.

This topic is not built in this repository yet. The folder holds only this file.

## How it would use `fsi_common`

The transaction stream would be a source, and each transaction a source unit anchored by its own identifier, for
example `tx:TX-1003`. Each alert the agent raises would be a fact citing the transactions behind it, with the rule
or score that raised it recorded on the fact. A transaction the agent cannot place would be an open question for
the analyst, and the analyst's approve or block answer would be a decision record with their name, role and date.
The unit accounting would show, for every transaction in the stream, whether it raised an alert or was cleared
with a reason, so no transaction goes unreviewed without a record.

Review desk, the shared reviewer's application, serves every topic folder that holds a `review_app/plugin.py`, as topic 03 does. This topic would add one, and its decisions and sign-offs would then be made on the same pages and in the same records.
