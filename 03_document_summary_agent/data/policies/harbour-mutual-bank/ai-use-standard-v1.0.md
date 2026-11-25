# Artificial Intelligence Use Standard

## Document control

Reference: HMB-STD-AI-014
Document type: Standard
Version: 1.0
Status: In force
Owner: Head of Data and AI Governance
Approved by: Executive Risk Committee, under the delegation in section 5 of the Policy Governance Framework (HMB-FRM-GOV-000)
Approval date: 30 June 2026
Effective date: 1 August 2026
Next review: June 2028

## 1. Purpose

1.1 This standard implements section 6 of the Model Risk Management Policy (HMB-POL-MRM-004) for AI Systems, and sets the requirements the Bank follows when it develops, buys, puts into service or uses an AI System.

1.2 It sets out the Bank's arrangements as a provider and as a deployer of AI Systems under Regulation (EU) 2024/1689 laying down harmonised rules on artificial intelligence, for the AI Systems the Bank uses in the European Union or whose output is used there.

1.3 This is the first version of this standard. Before it took effect, the Bank's AI Systems were governed only as models under the Model Risk Management Policy (HMB-POL-MRM-004).

## 2. Scope

2.1 This standard applies to every AI System that Harbour Mutual Bank plc or Harbour Mutual Bank Europe DAC develops, buys, puts into service or uses, and to every member of staff and contractor who operates or uses one.

2.2 Harbour Mutual Bank Europe DAC deploys a consumer credit scoring system, supplied by Brindlemoor Analytics Ltd, to assess the creditworthiness of applicants for personal loans in Ireland. The Bank treats the consumer credit scoring system as a high-risk AI System and Harbour Mutual Bank Europe DAC as its deployer.

2.3 The Bank puts a customer chat assistant into service under its own name for its customers in the United Kingdom and in Ireland. The Bank's customer chat assistant answers questions about accounts, payments and the Bank's products and passes conversations to a member of staff when the customer asks or when it cannot answer. The Bank is its provider.

2.4 The mortgage affordability model of Harbour Mutual Bank plc is used to inform lending decisions in the United Kingdom only, and its output is not used in the European Union. It is governed as a model under the Model Risk Management Policy (HMB-POL-MRM-004) and is recorded in the AI inventory under section 4.

2.5 Where an AI System is also a model, the Model Risk Management Policy (HMB-POL-MRM-004) applies to it in full, and this standard adds to it.

## 3. Definitions

3.1 Terms with capital letters have the meaning the Policy Governance Framework (HMB-FRM-GOV-000) gives them.

3.2 "High-risk AI System" means an AI System that the Bank has classified as high-risk under section 4, including every AI System it uses to evaluate the creditworthiness of natural persons or to establish their credit score.

3.3 "Provider" means the person that develops an AI System, or has it developed, and places it on the market or puts it into service under its own name or trademark.

3.4 "Deployer" means the person using an AI System under its authority in the course of its business.

3.5 "AI System Owner" means the executive accountable for the business use of an AI System.

## 4. AI inventory and classification

4.1 The Head of Data and AI Governance keeps an inventory of every AI System of the Bank, recording for each its purpose, its AI System Owner, whether the Bank is its provider or its deployer, the entities and countries in which it is used or its output is used, its classification and its tier under the Model Risk Management Policy (HMB-POL-MRM-004).

4.2 Before an AI System is first used, the Head of Data and AI Governance classifies it, recording whether it is a prohibited practice, a High-risk AI System, an AI System subject to transparency requirements or none of these, with the reasons for the classification.

4.3 For every AI System that is a model, the assessment of complexity under clause 6.3 of the Model Risk Management Policy (HMB-POL-MRM-004) includes an assessment of the system's interpretability, its explainability to the people affected by its output, its transparency and the potential for designer or data bias, and of the tests that will detect bias in use.

4.4 The Head of Data and AI Governance reviews each classification at least once a year and whenever the AI System, its use or its provider's instructions change.

## 5. AI literacy

5.1 Every member of staff who operates or uses an AI System, and every contractor who does so on the Bank's behalf, completes AI literacy training suited to their role, their technical knowledge and the context in which the AI System is used, before their first use of it and at least once a year after that.

5.2 Training for staff who use a High-risk AI System also covers the system's capabilities and limitations, the risks to the people on whom it is used and how to exercise human oversight of it.

5.3 The Head of Data and AI Governance keeps the record of the training completed and reports completion rates to the Executive Risk Committee each quarter.

## 6. Use of High-risk AI Systems

6.1 Harbour Mutual Bank Europe DAC uses the consumer credit scoring system, and every other High-risk AI System it deploys, in accordance with the instructions for use that accompany the system. The AI System Owner keeps those instructions, and changes to the way the system is used are approved by the Head of Data and AI Governance before they are made.

6.2 Human oversight of each High-risk AI System is assigned to named credit officers who have the competence, training and authority to understand the system's output, to decide not to use it in a particular case and to override it, and who have the support they need to do so.

6.3 To the extent Harbour Mutual Bank Europe DAC controls the input data of a High-risk AI System, the AI System Owner makes sure that the input data are relevant and sufficiently representative for the system's intended purpose, applying the data standards in section 7 of the Model Risk Management Policy (HMB-POL-MRM-004).

6.4 The AI System Owner monitors the operation of each High-risk AI System on the basis of its instructions for use and informs the provider of what monitoring shows where relevant. Where there is reason to consider that use of the system may present a risk to health, safety or fundamental rights, the Head of Data and AI Governance suspends its use and informs the provider and the market surveillance authority without undue delay. A serious incident is reported first to the provider and then to the market surveillance authority, at once.

6.5 Logs generated by the consumer credit scoring system are kept for 90 days and then deleted, in line with the retention period that the Bank's data retention schedule sets for operational logs.

6.6 Applicants are told that an automated system was used in assessing their application when they ask the Bank how a decision on it was made.

6.7 An applicant whose application is refused may ask for the decision to be reviewed by a credit officer through the Bank's complaints procedure, and the credit officer tells the applicant the outcome of the review.

6.8 A data protection impact assessment is completed and approved by the Data Protection Officer before any High-risk AI System is first used, and is reviewed whenever the system or its use changes.

## 7. Transparency of the chat assistant

7.1 The Bank's customer chat assistant tells each customer at the start of every conversation that they are talking to an automated assistant and not to a member of staff, in a clear and distinguishable way that meets the Bank's accessibility requirements.

7.2 A customer may ask at any point in a conversation to speak to a member of staff, and the assistant passes the conversation on with its history.

7.3 The Bank's customer chat assistant does not make lending decisions or give financial advice, and it is designed so that it does not do so.

## 8. Prohibited practices

8.1 The Bank does not place on the market, put into service or use any AI System for a practice that Article 5 of Regulation (EU) 2024/1689 prohibits, including systems that exploit the vulnerabilities of customers due to their age, disability or social or economic situation, and systems that evaluate or classify people on the basis of their social behaviour or personal characteristics.

8.2 The classification under clause 4.2 records for each AI System that it is not a prohibited practice, with the reasons.

## 9. Buying AI Systems

9.1 An Arrangement for an AI System supplied by an ICT Third-Party Service Provider is managed under the ICT Third-Party Risk Standard (HMB-STD-ICT-011).

9.2 Before an AI System is bought, the AI System Owner obtains from its provider the instructions for use, a description of its intended purpose, its known limitations and the information the Bank needs to meet this standard, and the Head of Data and AI Governance confirms that the information is sufficient.

9.3 For a High-risk AI System, the Arrangement requires the provider to tell the Bank of any change to the system, its instructions for use or its performance that may affect the Bank's use of it.

## 10. Roles

10.1 The Head of Data and AI Governance owns this standard, keeps the AI inventory and the classifications, and reports on the Bank's AI Systems to the Executive Risk Committee each quarter.

10.2 Each AI System Owner is accountable for the use of their AI System within this standard, including its human oversight, its monitoring and its records.

10.3 The Data Protection Officer advises on every AI System that processes personal data and approves the data protection impact assessments under clause 6.8.

10.4 The Head of Model Risk, under the Model Risk Management Policy (HMB-POL-MRM-004), keeps every AI System that is a model in the model inventory and in the validation plan.

## 11. Review of this standard

11.1 The Head of Data and AI Governance reviews this standard under section 6 of the Policy Governance Framework (HMB-FRM-GOV-000), and also when the Bank begins to use a new kind of AI System or a law that applies to the Bank's AI Systems changes.
