# KYC onboarding

In the FSI hackathon starter this topic builds a LangGraph agent that checks a new bank customer: it pulls the
customer's details out of their application, screens the name against sanctions and PEP lists, scores the risk,
sends high-risk customers to a person for review and writes a decision memo.

This topic is not built in this repository yet. The folder holds only this file.

## How it would use `fsi_common`

Each application would be a source, and each field of it (the name, the date of birth, the country of residence)
a source unit anchored by the application's own identifiers, for example `field:CUST-001/date_of_birth`. Each
screening match would be a fact citing the application field and the list entry it matched, with the match rule
recorded on the fact. A name that matches a list entry only in part, or a field the application leaves empty,
would be an open question for the compliance officer. The officer's risk decision would be a decision record with
their name, role and date, and the memo would be signed off the same way a compliance brief is.
