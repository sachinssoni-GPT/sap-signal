*A 30-hour global brownfield conversion with no Plan B — what an architect must check first.*

## This week's Signal

**Preh completes S/4 conversion with 30-hour window and no Plan B**

Preh executed a global S/4 brownfield conversion with a single 30-hour go-live window and no fallback plan. The cutover began on 14 November 2025 and used 102 testers; the actual overrun was 45 minutes versus a one-hour buffer. Post-migration, SAP HANA reporting is reported to be ten times faster and Fiori reduced transaction steps.

**What it changes:** For SAP landscapes with production-critical supply chains, this raises the bar for cutover discipline and rehearsal costs: tight blackout windows mean higher risk if rehearsal, partner coordination or interface validations are incomplete, and may require budget for extended hypercare.

Source: [E3 Magazine](https://e3mag.com/en/30-hours-of-downtime-and-zero-leeway-for-the-s4-conversion-at-preh/)

## The Architect's Take

### What a 30‑hour S/4 cutover rewrites on your checklist

*What it means for your landscape · I walk a cutover from the control room to the middleware queue and explain what to check first when a single, short brownfield window is all you get.*

**A quiet war room, a short clock**

It’s 02:00 on go‑live weekend. The screens show job queues and last‑minute transports. People speak in short, specific phrases; no one is rehearsing Plan B because there isn’t time for long debates.

Fact: the conversion began on 14 Nov 2025 [5]. The planned cutover window was 30 hours [1], and the operational buffer had been one hour; the team recorded an actual delay of 45 minutes against that buffer [2]. Preh chose a global big‑bang—every location at once, not a phased rollout [3]. One hundred and two testers worldwide gradually confirmed the release of their system areas [4]. The brownfield route was a 1:1 system conversion, after two preparatory projects: New General Ledger and migration to the central SAP Business Partner model [6].

My judgement: when the clock is that tight the room’s mood changes from “we’ll recover” to “we must not create extra failure modes.” That difference should change checklists and team behaviours immediately.

**What I check first in the landscape — in order**

Start where the cutover will break things: interfaces. With a 30‑hour single window you cannot rely on slow manual reconciliation. I verify middleware queues, synchronous API timeouts, IDoc retry policies, file ingestion schedules and any handoffs to third‑party systems. Confirm who will flip endpoints and how DNS, TLS certificates and endpoint credentials are rotated.

Next, check the system conversion mechanics. For a 1:1 brownfield conversion you need clear client locks, transport order of operations, database consistency checks, and a tested path to replay the conversion steps. The prior New GL and Business Partner projects mean masters and ledgers are already structurally different—confirm Post‑Conversion reconciliation scripts across finance and master‑data consumers.

Then custom code and interfaces. Line up custom reports, enhancements, user exits and scheduled jobs that touch master data or accounting tables. Prioritise anything that runs in night batches or that assumes old master formats—those are the usual surprises.

Finally, contracts and operational handoffs. With a big‑bang you must know who owns a failing interface: internal teams, an SI, a managed‑service provider or a cloud connector. Ensure SLAs, emergency contacts and escalation ladders are current and reachable during the window.

My judgement: the single‑window, global cutover increases the dependency surface. You cannot treat any interface as low‑risk; every external consumer becomes a potential showstopper.

**Teams, tests and the two things to do Monday**

Operationalise the testers. One hundred and two testers worldwide signed off on parts of the landscape [4]. That distributed sign‑off is invaluable—but it only matters if you can map each tester’s scope to your post‑go‑live severity matrix.

Treat the 45‑minute swing against a one‑hour buffer as a warning, not a victory [2]. A small slippage exposed brittle sequencing and optimistic assumptions about cutover tasks.

My judgement: short, single‑window cutovers with a big‑bang deployment favour repeatability over improvisation. They demand exact checklists, automation of the boring steps, and clearly owned fallbacks (even if the plan is to stay live). The absence of phased rollback options means compensating controls and reconciliation must be near‑instant.

First two things to do on Monday:
1) Produce a cross‑map that links every interface, job and custom object to a named on‑call owner and an explicit rollback or compensation action. Make it visible to every tester and ops person.
2) Automate and rehearse the three highest‑risk interfaces: mock‑fail them, confirm automatic retries and document the manual intervention steps if automation fails.

If you do those two things, you make a tight window survivable; if you don’t, it stays a gamble.

**What to watch**

- Publication of Preh’s detailed post‑conversion report and incident log from the 14 Nov 2025 cutover [5]

## 1 thing that moved

**1. Cole Haan completes global SAP S/4HANA go-live across three regions in 18 months**
*ECC exit & S/4HANA*

Cole Haan went live on SAP S/4HANA after an 18-month program that delivered a single global cutover and preserved business continuity, according to Applexus on Nov. 11, 2026. The rollout replaced a 20-year-old AFS environment across North America, Europe and Asia and established a cloud enterprise data platform and AI foundation.

**What it changes:** A single global S/4HANA cutover that retires a 20-year AFS instance reduces integration cost and technical debt while creating a unified data foundation that accelerates analytics and AI investments—impacting near-term migration spend and ongoing maintenance.

Source: [PR Newswire](https://www.prnewswire.com/news-releases/cole-haan-completes-global-sap-s4hana-transformation-across-three-regions-in-18-months-with-applexus-ai-powered-delivery-302935892.html) · vendor source, not independently confirmed

## Deadline Radar

Dated SAP changes to plan around, soonest first.

- **31 Dec 2027** · Mainstream maintenance ends for BW 7.5 · *SAP BW 7.5* · in ~14 months ([source](https://www.riministreet.com/blog/sap-end-of-mainstream-maintenance-deadlines-are-looming-for-gts-bobj-bpc-bw-hybris/))
- **31 Dec 2027** · Mainstream maintenance ends for ECC 6.0 (EHP 6-8) · *SAP ECC 6.0 / Business Suite 7* · in ~14 months ([source](https://www.dvwanalytics.com/blog/sap-ecc-end-of-support-a-practical-primer))
- **31 Dec 2027** · Mainstream maintenance ends for PI/PO 7.5 · *SAP Process Orchestration 7.5* · in ~14 months ([source](https://leverx.com/en-gb/blog/sap-pi-po-to-integration-suite-migration-uk))
- **31 Dec 2030** · Optional extended maintenance ends (2-point premium) · *SAP ECC 6.0 / Business Suite 7* · in ~4 years ([source](https://www.panorama-consulting.com/18-months-to-the-sap-ecc-cliff-and-half-of-customers-still-havent-moved/))
- **31 Dec 2030** · Optional extended maintenance ends for PI/PO 7.5 · *SAP Process Orchestration 7.5* · in ~4 years ([source](https://leverx.com/en-gb/blog/sap-pi-po-to-integration-suite-migration-uk))
- **31 Dec 2030** · SAP ends third-party database resale/support and Java support for Business Suite 7 · *SAP Business Suite 7 on third-party databases* · in ~4 years ([source](https://sapinsider.org/blogs/sap-sets-2030-cutoff-for-third-party-database-and-java-support/))
- **Dec 2033** · ERP private edition transition option ends (selected RISE customers) · *SAP ERP, private edition, transition option* · in ~7 years ([source](https://sapinsider.org/blogs/what-erp-support-deadlines-actually-mean-for-companies/))

## Sources for the Take

1. The planned time window for the go-live was 30 hours. ([E3 Magazine](https://e3mag.com/en/30-hours-of-downtime-and-zero-leeway-for-the-s4-conversion-at-preh/))
2. The actual delay was 45 minutes, compared to a planned buffer of one hour. ([E3 Magazine](https://e3mag.com/en/30-hours-of-downtime-and-zero-leeway-for-the-s4-conversion-at-preh/))
3. Preh opted for a global “big bang” approach: all locations at the same time, rather than a phased rollout. ([E3 Magazine](https://e3mag.com/en/30-hours-of-downtime-and-zero-leeway-for-the-s4-conversion-at-preh/))
4. 102 testers worldwide gradually confirmed the release of their system areas. ([E3 Magazine](https://e3mag.com/en/30-hours-of-downtime-and-zero-leeway-for-the-s4-conversion-at-preh/))
5. On Friday, November 14, 2025, the conversion began. ([E3 Magazine](https://e3mag.com/en/30-hours-of-downtime-and-zero-leeway-for-the-s4-conversion-at-preh/))
6. The brownfield approach used a 1-to-1 system conversion, with two preliminary projects before migration: the implementation of the New General Ledger and the migration to the central SAP Business Partner master data model. ([E3 Magazine](https://e3mag.com/en/30-hours-of-downtime-and-zero-leeway-for-the-s4-conversion-at-preh/))

---

*The SAP Signal* is curated and signed off by Sachin. Public sources only; views are my own.
