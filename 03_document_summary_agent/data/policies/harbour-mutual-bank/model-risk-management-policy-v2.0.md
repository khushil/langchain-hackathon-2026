# Model Risk Management Policy

## Document control

Reference: HMB-POL-MRM-004
Document type: Policy
Version: 2.0
Status: In force
Owner: Chief Risk Officer
Approved by: Board of Directors of Harbour Mutual Bank plc, on the recommendation of the Board Risk Committee; adopted by the board of directors of Harbour Mutual Bank Europe DAC on 5 March 2026
Approval date: 26 February 2026
Effective date: 1 March 2026
Next review: February 2028
Supersedes: HMB-POL-MRM-004 version 1.3 of 3 May 2024

## 1. Purpose

1.1 This policy sets out how Harbour Mutual Bank identifies, measures, manages and controls model risk: the potential for adverse consequences from errors in models or from the inappropriate use of their outputs to inform business decisions.

1.2 The Bank treats model risk as a risk in its own right. This policy is intended to meet the expectations of the Prudential Regulation Authority's supervisory statement SS1/23 on model risk management principles for banks, and it is the board-approved model risk management policy of the Bank.

1.3 This version brings vendor models and the models of Harbour Mutual Bank Europe DAC into the firm-wide inventory, sets the revalidation frequency by tier and refers the additional requirements for models that are AI Systems to the Artificial Intelligence Use Standard (HMB-STD-AI-014).

## 2. Scope

2.1 Harbour Mutual Bank plc holds permission from the Prudential Regulation Authority to use the internal ratings based approach to calculate its capital requirements for credit risk on its residential mortgage portfolio.

2.2 This policy applies to every model that Harbour Mutual Bank plc or Harbour Mutual Bank Europe DAC develops, buys, uses or decommissions, including vendor models, models used for financial reporting and models that are AI Systems, whatever the business line or entity that uses them.

2.3 Deterministic quantitative methods that are not models, such as decision rules and calculators, are within this policy only as clause 3.3 sets out.

## 3. Definitions

3.1 A model is a quantitative method, system, or approach that applies statistical, economic, financial, or mathematical theories, techniques, and assumptions to process input data into output. The definition of a model includes input data that are quantitative and / or qualitative in nature or expert judgement-based, and output that are quantitative or qualitative.

3.2 Model use means using a model's output as a basis for informing business decisions.

3.3 Where a deterministic quantitative method that is not classified as a model has a material bearing on business decisions and is complex in nature, the Head of Model Risk decides whether the relevant parts of this policy apply to it. Every other deterministic quantitative method is subject to documented management controls set by its owner.

3.4 Terms with capital letters that this section does not define have the meaning the Policy Governance Framework (HMB-FRM-GOV-000) gives them.

## 4. Governance

4.1 The Board approves this policy on the recommendation of the Board Risk Committee and reviews it under section 6 of the Policy Governance Framework (HMB-FRM-GOV-000), taking account at each review of the Bank's model risk profile, the economic and business environment, the regulatory requirements that apply to the Bank and the new technologies the Bank uses.

4.2 The Chief Risk Officer sets the Bank's model risk appetite each year, with measures for the effectiveness of the model risk management framework, for model approval, for limits on model use and exceptions, for thresholds of acceptable model performance and for the use of post-model adjustments, and reports performance against it to the Board Risk Committee each quarter.

4.3 The Chief Risk Officer, who holds the SMF4 senior management function, has overall responsibility for the model risk management framework, its implementation and its execution and maintenance. The Chief Risk Officer's Statement of Responsibilities records this responsibility.

4.4 The Model Risk Committee, chaired by the Chief Risk Officer, approves models of tier 1 and tier 2 for use, approves material model changes, decides on restrictions of model use and oversees the model inventory. Models of tier 3 are approved by the Head of Model Risk.

4.5 The Board receives a report at least twice a year, and the Board Risk Committee each quarter, on the Bank's model risk profile against its model risk appetite, covering the effectiveness of the control framework and of model use, the significant model risks from individual models and in aggregate, significant changes in model performance and the extent to which this policy is followed.

4.6 The Board challenges the outputs of the Bank's most material models when they are presented to it, including the internal ratings based models, and is briefed on their capabilities and limitations, their operating boundaries, the potential impact of poor performance and the mitigants in place.

## 5. Model inventory

5.1 The Head of Model Risk keeps a firm-wide inventory of every model in use at Harbour Mutual Bank plc and Harbour Mutual Bank Europe DAC. For each model the inventory records its purpose and use, its operating boundaries, its assumptions and limitations, the findings of its validation with any open remediation actions, and its governance details, including its owner, its validator, the date of its last validation and the date of its next.

5.2 Each model owner keeps the inventory entries for their models accurate and up to date, and confirms them to the Head of Model Risk each quarter.

5.3 The inventory records the dependencies between models, including each model whose output is the input of another, so that the Bank can understand its aggregate model risk.

## 6. Model tiering

6.1 Every model is assigned a tier from 1, the highest risk, to 3, using one firm-wide approach that rates each model's materiality and complexity.

6.2 Materiality takes account of quantitative measures, such as the exposure, book value or number of customers to which the model applies, and of the importance of the model to the business decisions it informs and its potential impact on the Bank's solvency and financial performance.

6.3 Complexity takes account of the nature and quality of the input data, the methodology and its assumptions, the demands of implementation and the frequency of use, and, for models that use advanced techniques, the use of alternative or unstructured data and the model's interpretability, explainability and transparency and the potential for designer or data bias. For models that are AI Systems, the complexity rating also takes account of the assessment the Artificial Intelligence Use Standard (HMB-STD-AI-014) requires.

6.4 The tier of each model is reassessed by the validation function at each validation and revalidation. The tiering approach itself is reviewed every two years by the Head of Model Validation.

## 7. Model development

7.1 Every model has a statement of its purpose and design objectives. Its design, the choice of variables and parameters and its assumptions are suitable for its intended use and conceptually sound.

7.2 The model developer shows that the data used to develop the model are suitable for its intended use, are consistent with the chosen theory and methodology, are representative of the portfolios, products or customers the model is used for and contain no inappropriate bias. Data adjustments and proxies are documented and validated.

7.3 Development testing shows that the model works as intended, using backward-looking tests on actual observations, forward-looking tests on plausible scenarios with sensitivity analysis, and, where practicable, comparison with challenger models. The developer provides the outline of the monitoring pack that will be used to monitor the model in use.

7.4 Every model has comprehensive and up-to-date documentation of its design, theory and logic, detailed enough for an independent expert to understand how it works, identify its key assumptions and limitations and replicate its results. For a vendor model, the documentation is detailed enough to validate the Bank's use of it.

7.5 Models are implemented in systems that have been tested for their purpose and are under quality control and change control. The suitability of those systems is reassessed every three years.

## 8. Independent validation

8.1 The Model Validation team, led by the Head of Model Validation, validates the Bank's models. It operates independently of model development and of model owners, with a reporting line to the Chief Risk Officer that is separate from the reporting lines of model developers and model owners, and the Head of Model Validation has direct access to the Board Risk Committee.

8.2 Every model is independently reviewed before its first use, covering its inputs, calculations and outputs, the conceptual soundness of its theory and its suitability for its intended use, the quality of the development evidence and the judgements made in its development. The depth of the review is set by the model's tier.

8.3 Model owners monitor the performance of their models against the thresholds set at development, at a frequency set by tier, and the Model Validation team reviews the monitoring reports.

8.4 Every model is revalidated at a frequency set by its tier: models of tier 1 at least once a year, models of tier 2 at least once every two years and models of tier 3 at least once every three years.

8.5 The Model Validation team makes a recommendation on each model's approval to the Model Risk Committee or the Head of Model Risk, and the approving body makes sure the validation's recommendations for remediation are carried out.

## 9. Vendor and group models

9.1 For a vendor model, the model owner validates the Bank's own use of the model and monitors its performance and outcomes against the Bank's own data.

9.2 Where Harbour Mutual Bank Europe DAC uses a model developed by Harbour Mutual Bank plc, the Model Validation team confirms that the data and assumptions are relevant to its use by Harbour Mutual Bank Europe DAC and that the validation is adequate for the model's tier measured against the risk profile of Harbour Mutual Bank Europe DAC on its own.

9.3 Vendor models that are AI Systems are also subject to the Artificial Intelligence Use Standard (HMB-STD-AI-014), and their contracts to the ICT Third-Party Risk Standard (HMB-STD-ICT-011).

## 10. Model risk mitigants

10.1 Post-model adjustments, including overlays, management adjustments and overrides of model output, are proposed by the model owner with a written justification and the method of calculation, approved by the Model Risk Committee and recorded in the inventory with the date by which each adjustment is to be reduced or removed.

10.2 Model results that include post-model adjustments are reported with and without them, so that their effect is clear to the people who use the results.

10.3 Where validation finds significant deficiencies or errors in a model, or performance tests show that a significant breach has occurred or is likely, the Model Risk Committee may permit the model's use only under strict controls or mitigants, or limit or prohibit its use for specific purposes. Each restriction and the status of its remediation are recorded in the inventory and reported to the model owner, the model users, the Model Validation team and senior management.

10.4 Where the same post-model adjustment is used repeatedly for the same limitation, the Head of Model Risk asks the model owner to consider whether the model should be recalibrated or redeveloped.

## 11. Internal audit

11.1 Internal Audit assesses periodically, and at least once every three years, the effectiveness of the model risk management framework across each stage of the model lifecycle, the effectiveness of the framework as a whole and how far this policy is followed. Internal Audit reports its findings to the Board Risk Committee and the Audit Committee.

11.2 The audit verifies that this policy and its procedures enable model risks to be identified and managed, that the risk controls and validation are adequate for the level of model risk, that the validation staff have the experience, standing and incentives to give an objective opinion, and that model owners and the control functions follow this policy.

## 12. Roles and responsibilities

12.1 Model owners are documented for every model in the inventory. A model owner is accountable for monitoring the model's performance against the Bank's model risk appetite, for the model's tier and validation, for giving the validators the information they need and for the model's inventory entry.

12.2 Model users are documented for every model. A model user is accountable for using the model only for its intended purpose and for taking its known limitations into account when using its output.

12.3 Model developers are documented for every model. A model developer is accountable for developing, testing and documenting the model under section 7.

12.4 The Head of Model Risk leads the Model Risk function in the second line of defence, keeps the inventory and the tiering approach, and reports on model risk to the Chief Risk Officer.

12.5 The Model Risk function sets out in procedures how this policy is applied to each model type, with any additional standards for material and complex model types.
