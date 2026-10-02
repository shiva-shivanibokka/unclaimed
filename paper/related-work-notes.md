# Related-work notes

Companion to `references.bib`. Every entry was checked on 2026-10-01: arXiv entries against their arXiv abstract page (title, authors, date), journal/book entries against their Crossref or OpenAlex DOI record, the NAACL 2007 paper against the ACL Anthology, the Georgetown report against its Digital Government Hub page, and PolicyEngine-US against its GitHub repository. Summaries come from the abstracts; "Relation" lines are our framing for the paper and should be checked against the full texts before submission.

Venue notes in the bib come from the arXiv comment field or the publisher. Where no venue is given, cite as an arXiv preprint.

## 1. Tool-using conversational agents with simulated users; reliability metrics

| Key | What it does | Relation to our work |
|---|---|---|
| `yao2024taubench` | Benchmark where an LLM-simulated user talks to a tool-using agent bound by domain policy; scores the final database state and introduces pass^k for consistency across trials. | Closest evaluation design to our Tier C; we keep the simulated-user setup but score a determination against an exact rules-engine reference and focus on one asymmetric error (false "you qualify"). |
| `barres2025tau2bench` | Extends tau-bench to a dual-control setting where the user also acts through tools, with a compositional task generator and a tool-constrained user simulator. | Shows that user-simulator fidelity and agent/user coordination dominate errors; our task is single-control (the person only answers), and our oracle tiers (A/B) remove the simulator entirely. |
| `lu2024toolsandbox` | Stateful, conversational benchmark for LLM tool use with an on-policy user simulator and milestone-based evaluation. | Another simulated-user tool benchmark; it measures whether the agent completes tasks, while our E3 asks where decisions should live. |
| `liu2023agentbench` | Multi-environment benchmark of LLMs acting as agents (OS, database, web, games). | Broad capability benchmark; motivates our narrower, decision-focused evaluation. |
| `wang2023mint` | Evaluates LLMs in multi-turn interaction with tools and natural-language feedback. | Multi-turn tool use with feedback; in our design the tool, not the model, controls the turn sequence. |
| `rabanser2026agentreliability` | Proposes twelve reliability metrics (consistency, robustness, predictability, safety) and finds capability gains have barely improved reliability across 12 frontier models. | Supports our claim that accuracy alone hides the failures that matter; our design makes question choice and stopping deterministic, so run-to-run consistency comes from the design. |
| `raj2026consistency` | Statistical framework (U-statistics, kernel trajectory metrics) for agent consistency under meaning-preserving perturbations. | A possible method for measuring consistency in E3 across rephrased simulated people. |

## 2. Clarifying questions, information seeking, value-of-information question selection with LLMs

| Key | What it does | Relation to our work |
|---|---|---|
| `rao2018learning` | Ranks clarification questions by neural expected value of perfect information (EVPI). | Early EVPI-style question ranking in NLP; we compute the value of a question exactly by running the rules engine on low/high what-if answers instead of learning it. |
| `aliannejadi2019asking` | Introduces asking clarifying questions in open-domain information-seeking conversation (Qulac dataset, question selection). | Clarification for retrieval; our questions resolve facts about a household that a calculator needs. |
| `kuhn2022clam` | CLAM: the model detects when a question is ambiguous and asks for clarification only then. | Selective asking driven by the model's own uncertainty; we drive asking by whether an answer could change an eligibility result. |
| `tamkin2022taskambiguity` | Studies task ambiguity in humans and LMs and how models handle underspecified tasks. | Motivates explicit handling of unknowns; we make unknown and declined answers explicit state rather than something the model infers. |
| `li2023gate` | GATE: LLMs elicit human preferences by generating questions, examples, or edge cases. | LLM-driven elicitation; our E3 condition (b) is a model choosing its own questions, which we compare against code-chosen questions. |
| `zhang2023twentyq` | Probes multi-turn planning of LLMs via the 20 Questions game. | Standard testbed for LLM question planning; our setting has a known, executable answer function (the rules engine), so value of information can be computed rather than estimated. |
| `hu2024uot` | Uncertainty of Thoughts: LLM simulates possible futures and picks questions by an information-gain reward. | Information-gain question selection done by the LLM; ours is done by code over exact simulations, with the LLM only phrasing. |
| `andukuri2024stargate` | STaR-GATE: trains an LM to ask useful clarifying questions via self-improvement with a simulated user. | Learned questioning; ours is not trained and is the same on every run. |
| `li2024mediq` | MediQ: benchmark and framework for question-asking LLMs in interactive clinical reasoning, with abstention when information is insufficient. | Closest high-stakes analogue (ask before deciding, abstain when unsure); we likewise give conditional results instead of guessing, but decisions come from a rules engine. |
| `choudhury2025bedllm` | BED-LLM: sequential Bayesian experimental design that chooses LLM questions to maximize expected information gain (20 Questions, preference elicitation). | The most direct LLM value-of-information method; it needs an LLM-based belief model, whereas our "belief" is a set of what-if households scored by the exact engine. |
| `hartmann2026amortising` | Amortises Bayesian experimental design into an LLM policy via RL with an expected-information-gain reward. | Recent workshop paper; shows the field moving toward learned EIG policies, in contrast to our explicit computation. |

## 3. LLM as interface, symbolic engine decides; tool-augmented LLMs

| Key | What it does | Relation to our work |
|---|---|---|
| `karpas2022mrkl` | MRKL: modular architecture routing between an LLM and discrete expert modules (calculators, APIs, knowledge bases). | Early statement of "LLM plus discrete reasoning modules"; we go further and take control flow (what to ask, when to stop) away from the model as well. |
| `schick2023toolformer` | LMs teach themselves when to call tools (calculator, search, etc.). | Brief mention: the model decides when to use a tool; in our design the model never decides. |
| `yao2022react` | ReAct: interleaves reasoning traces and tool actions. | The default agent loop that our condition (b) resembles. |
| `qin2023toolllm` | ToolLLM/ToolBench: instruction tuning for using thousands of real APIs. | Tool-use scale; not about who owns the decision. |
| `li2023apibank` | API-Bank: benchmark for tool-augmented LLMs. | Tool-use benchmark; brief mention only. |
| `gao2022pal` | PAL: the LLM writes a program and an interpreter computes the answer. | Delegates arithmetic to code, as we do; we also never let the model write the rules. |
| `lyu2023faithfulcot` | Faithful CoT: translate a query into a symbolic chain, then solve it with a deterministic solver. | Same "translate, then solve deterministically" idea for reasoning tasks. |
| `pan2023logiclm` | Logic-LM: LLM formalizes the problem, a symbolic solver infers, with self-refinement on solver errors. | Neuro-symbolic reasoning; the formalization step is still the model's, while our rules are fixed code (PolicyEngine). |
| `ye2023satlm` | SatLM: LLM writes a declarative spec solved by a SAT/SMT solver. | Same split; our "spec" is the household, filled in from tracked answers. |
| `olausson2023linc` | LINC: LLM translates to first-order logic and a prover decides. | Same split; shows the translation step is the main error source, which is why we validate answers and read them back. |

## 4. LLM errors in legal, tax and public-benefits domains; rules as code; benefits screening

| Key | What it does | Relation to our work |
|---|---|---|
| `dahl2024legalfictions` | Profiles legal hallucinations in LLMs at scale and finds high rates and overconfidence. | Evidence that fluent models assert wrong legal facts with confidence: the failure behind our false "you qualify" metric. |
| `magesh2024hallucinationfree` | Finds that commercial retrieval-augmented legal research tools still hallucinate. | RAG does not remove the problem, which supports our move of the decision into code. |
| `holzenberger2020sara` | SARA: statutory reasoning dataset over US tax law, with a Prolog encoding of the statutes. | Early rules-as-code-plus-NLP dataset; shows symbolic encodings solve cases that language models miss. |
| `blairstanek2023statutory` | Tests GPT-3 on SARA and finds it errs on statutory reasoning, including on simple synthetic statutes. | Direct evidence that LLMs misapply tax statutes. |
| `nay2023taxattorneys` | Evaluates LLMs on tax-law questions; accuracy improves with newer models and retrieval but stays below expert level. | Tax questions answered by models alone, our E3 condition (c). |
| `bock2025taxcalcbench` | TaxCalcBench: frontier models compute fewer than a third of simplified federal returns correctly, misusing tax tables and eligibility rules. | Most direct evidence that models should not do the arithmetic or eligibility logic; our engine does both. |
| `gosciak2026socialservices` | 770-question SNAP and social-services benchmark plus a randomized trial: correct chatbot suggestions raise caseworker accuracy, incorrect ones sharply lower it. | Closest benefits-domain study; shows wrong confident answers cause real harm, which our design targets. |
| `jo2025trustburden` | Interviews SNAP applicants about LLM-assisted benefits systems; LLMs reduce some administrative burdens but add new ones and invite overtrust. | Human-side motivation for not letting the model decide and for stating unknowns. |
| `sunny2025neurosymbolic` | Neuro-symbolic framework: LLM encodes CalFresh rules into a formal ontology and an SMT solver checks whether eligibility explanations follow the law. | Closest neuro-symbolic benefits work; it audits explanations after the fact, while we compute the determination with an existing rules engine and run the interview from it. |
| `liu2026civi` | CIVI: diagnoses failures of search agents answering civic/government questions; none match an attentive human. | Public-sector LLM errors; retrieval does not fix them. |
| `merigoux2021catala` | Catala: a programming language for faithfully encoding legislation (e.g. tax and benefits rules). | Rules-as-code foundation; PolicyEngine plays this role for us. |
| `mohun2020crackingcode` | OECD working paper defining and surveying Rules as Code in government. | Policy background for treating eligibility rules as executable code. |
| `kennan2025airulesascode` | Georgetown experiments using LLMs to translate SNAP and Medicaid policy into summaries, pseudocode and code; useful but needs human oversight for complex logic. | LLMs as rule authors; we use LLMs only as the interface over already-encoded rules. Grey literature (report, not peer-reviewed). |
| `policyengineus` | Open-source rules engine of the US tax-benefit system (AGPL-3.0). | Our calculator and reference; cite the pinned version. |

## 5. User simulation with LLMs for evaluating dialogue systems

| Key | What it does | Relation to our work |
|---|---|---|
| `schatzmann2006survey` | Survey of statistical user simulation for training/evaluating dialogue managers. | Classic background for Tier C. |
| `schatzmann2007agenda` | Agenda-based user simulator with goals and a stack of pending dialogue acts. | Goal-conditioned simulator design, like our persona-plus-household simulated person. |
| `terragni2023incontext` | Prompted (in-context) LLM user simulators for task-oriented dialogue, with error analysis. | Our simulated person is a prompted LLM of this kind. |
| `sekulic2024daus` | DAUS: fine-tuned LLM user simulator that stays more consistent with user goals and hallucinates less. | Simulator hallucination is a validity threat for us (a person who invents facts); we check the simulator's answers against the household. |
| `ulmer2024selftalk` | Bootstraps task-oriented agents from LLM self-talk between agent and simulated user. | Simulated dialogue for training, not evaluation; contrast. |
| `zhu2024reliablesimulator` | Limitations of LLM user simulators for conversational recommendation: data leakage, over-reliance on history, hard to control. | Threat-to-validity reference for Tier C. |
| `dou2025simulatorarena` | SimulatorArena: compares LLM user simulators with real human conversations as proxies for evaluating assistants. | Evidence on how far simulator-based scores track human ones; we state this limitation. |
| `naous2025userlm` | Trains dedicated user language models; finds assistant models role-playing users are unrealistically cooperative and inflate scores. | Directly relevant to our "same model family can flatter results" threat; motivates using a different model for the person. |
| `balog2025usersim` | Overview of user simulation in the generative-AI era (modeling, synthetic data, evaluation). | General reference for the method. |

## 6. Classic decision-theoretic questioning and adaptive questionnaires

| Key | What it does | Relation to our work |
|---|---|---|
| `howard1966information` | Introduces information value theory: the value of a measurement is the expected improvement in decision value. | Theoretical root of our score: a question is worth asking only if its answer can change a decision. |
| `gorry1968sequential` | Sequential diagnosis program that picks the next test by expected value and stops when further tests are not worth their cost. | Direct ancestor of our ask/stop loop with question cost. |
| `heckerman1992pathfinder` | Pathfinder: normative (decision-theoretic) expert system that selects the next observation by value of information. | Classic expert-system interviewing; we reuse the idea with an exact rules engine in place of a probabilistic model. |
| `weiss1984cat` | Computerized adaptive testing: choose each item based on prior responses to reach precision with fewer items. | Adaptive questionnaires that stop early; our stop rule plays the role of CAT's precision-based stop. |
| `vanderlinden2000cat` | Edited volume on CAT theory and practice (item selection, stopping rules, exposure control). | Standard reference for item selection and stopping rules. |

## Could not verify or deliberately left out
- **Venues not added.** tau-bench, ToolSandbox, CLAM, GATE, MediQ, STaR-GATE, Toolformer, PAL, Rao & Daume III, Large Language Models as Tax Attorneys and others were published at conferences, but the arXiv records we checked do not state the venue, so the bib cites them as arXiv preprints. Add the venue only after checking the proceedings page (for example, Rao & Daume III is believed to be ACL 2018, not confirmed here).
- **arXiv API was rate-limited**, so verification used the arXiv abstract pages' citation metadata instead; results are the same records.
- **"20 Questions" with LLMs** beyond `zhang2023twentyq` and the BED papers: not added.
- **Lindley (1956) on expected information**, Wainer's *CAT: A Primer*, and Lord (1980): considered but not checked, so left out.
- **Nava PBC case studies** on AI for benefits caseworkers and the Code for America/Anthropic announcement: found only as web pages without a citable report, left out.
- **OpenFisca** and other rules-as-code engines: not checked, left out.
- One Crossref record lists the CAT book's second editor as "Gees A.W. Glas"; the bib uses the correct name "Cees A. W. Glas".
- PolicyEngine has no canonical paper we could confirm; it is cited as software (year = repository creation, 2021).
