*Four unauthenticated, maximum‑severity flaws this November mean you must treat ICM/Web Dispatcher, Gateway and SAML2 endpoints as compromised until proven otherwise.*

## This week's Signal

**SAP issues four maximum‑severity, unauthenticated flaws in November patch**

The November 2026 Security Patch Day disclosed four maximum‑severity flaws, including two 10.0 CVSS bugs in ICM/Web Dispatcher (ICM2SHELL) and a Gateway PROXYGATE issue that can treat external actors as internal servers. A SAML2 service‑provider weakness can let unauthenticated attackers impersonate any user, and SAP’s bulletin lists dozens of notes and advisories to apply and verify.

**What it changes:** Shared connectivity components mean many landscapes can be exposed at once and remediation will require coordinated patching, configuration changes and follow‑up testing—raising operational risk and near‑term maintenance cost.

Source: [ERP Today](https://erp.today/sap-security-patch-day-november-2026-shared-infrastructure/)

## The Architect's Take

### Mapping November's SAP maximum‑severity flaws

*What it means for your landscape · How to find which systems, interfaces, custom code and contracts are exposed, what to patch first, and two immediate checks for Monday.*

**A Monday status meeting that suddenly matters**

You’re on a routine programme call — release windows, downstream test schedules, the usual snag list — until security flags a bulletin. Operations and integration start naming components: Web Dispatcher, ICM, Gateway. The calendar fills with emergency slots.

Fact: SAP published four critical vulnerabilities this November affecting ICM, Web Dispatcher and Gateway; two ICM/Web Dispatcher flaws carry a 10.0 CVSS score (CVE-2026-76964 and CVE-2026-89126) [1], the Gateway issue Onapsis named PROXYGATE is CVE-2026-89103 [2], and a CSRF flaw rated 9.6 affects the administration interfaces in Web Dispatcher and ICM (CVE-2026-89119) [4]. GitHub advisories also cover SAP Cloud SDK packages and a sandbox project [5].

My judgment: treat this like a live incident. Maximum‑severity, unauthenticated issues are the kind that shorten debate and lengthen incident logs.

**Walk-your-landscape checklist — the order I’d run**

Start at the edge. Check public-facing Web Dispatchers and ICM endpoints first: the two 10.0 CVSS flaws hit those components directly [1]. Any instance reachable from the internet (or poorly behind reverse proxies) is highest risk because the two CVSS‑10 issues are associated with unauthenticated impact in the bulletin context [1].

Next, enumerate SAP Gateway instances and their fronting devices. PROXYGATE (CVE-2026-89103) is reported to allow unauthenticated attackers to run code and take control — treat that as immediate lateral‑movement risk until isolated or patched [2] [3].

Then map trust boundaries and administration paths. The CSRF issue affects admin interfaces and requires an administrator’s active session to exploit; identify which consoles are reachable from networks where admin sessions could originate [4].

Follow the call chains: load balancers, reverse proxies, SSO gateways, API gateways, B2B endpoints and partner VPNs. A compromised dispatcher or Gateway is a pivot into backend ABAP processes and service accounts. Also list middleware that depends on SAP Cloud SDK packages referenced in the GitHub advisories — they may provide secondary exposure paths [5].

Check custom code that parses HTTP headers, session cookies, or deserializes untrusted input. Flag any outsourced appliances, managed Web Dispatchers, or third‑party teams that hold admin credentials — they change your blast radius.

My judgment: patching is necessary, but the immediate priority is exposure mapping and containment so you don’t patch after an attacker already has a foothold.

**What to patch first, and the two checks to run on Monday**

Patch priority: 1) Public‑facing Web Dispatchers and ICM instances immediately — the two CVSS 10.0 flaws hit those components [1]. 2) Exposed SAP Gateway instances next — PROXYGATE allows code execution and full takeover if exploited [3]. 3) Harden admin consoles and session management because the CSRF flaw depends on active admin sessions [4].

Two things to run on Monday (do them before tea):

1) External exposure sweep — concrete steps and acceptance criteria.
• Tool examples: nmap and an HTTP probe. Run: nmap -Pn -p 80,443 --open -sV <target-range> and an HTTP title probe like: nmap -Pn -p 80,443 --script http-title <ip>. Then for each responsive host run: curl -k -I https://<host>/ and curl -k https://<host>/ -o /tmp/host.html to inspect for admin pages.
• What you’re looking for: any Web Dispatcher, ICM or Gateway UI or login page reachable from the internet. Acceptance: zero reachable admin consoles from untrusted networks; otherwise block at the firewall or WAF and isolate the IP immediately. (Fact: these components are the ones affected in this bulletin) [1] [2] [4].

2) Privileged‑session audit — concrete steps and acceptance criteria.
• Use your SAP admin tools (NWA/ABAP admin transactions such as SM04 or equivalent) to list active users and sessions that have admin privileges. Export sessions, note source IPs, and identify any remote admin sessions originating from untrusted networks.
• Actions: terminate unnecessary admin sessions, force logoff for sessions from unknown IPs, and rotate service and admin credentials exposed to third parties. Acceptance: no active admin sessions from untrusted addresses; all rotated credentials validated and recorded.

My judgment: these two checks stop obvious exploitation attempts, reduce immediate risk, and buy time to test and deploy vendor patches. Don’t wait to confirm exploit code in the wild — assume exposure until you verify otherwise.

**What to watch**

- SAP Security Notes and patch bundles for the affected CVEs (CVE-2026-76964, CVE-2026-89126, CVE-2026-89103, CVE-2026-89119)
- Updates to the GitHub advisories for SAP Cloud SDK packages and related sandbox projects

## Five things that moved

**1. AstraZeneca migrates to SAP Cloud ERP Private via RISE; adopts SAP Business AI**
*ECC exit & S/4HANA*

AstraZeneca is migrating its full SAP estate to SAP Cloud ERP Private through the RISE with SAP journey, expanding a 20-year relationship with SAP. The company’s Axial programme will move it from SAP ERP Central Component to Cloud ERP Private while exploring SAP’s Industry AI portfolio, the Joule solution and agentic AI use cases across finance, supply chain and manufacturing.

**What it changes:** Expect a large transformation budget and multi-year cloud programme to harmonize data and enable AI pilots; plan for substantial migration, governance and data-cleaning work to realize AI and sustainability integrations.

Source: [SAP](https://news.sap.com/2026/11/sap-expands-collaboration-astrazeneca-rise-with-sap-business-ai/) · developing

**2. SAP publishes product-level cloud emissions and energy data to customers**
*Data & AI*

SAP now provides product-level, customer-specific cloud emissions and energy data, making footprint data visible product by product. The approach uses a daily, bottom-up energy model that allocates server electricity (CPU, memory, PUE) to products and tenants, and the methodology is aligned to the GHG Protocol ICT guidance and published for customers.

**What it changes:** SAP-level, activity-based emissions per product gives architects actionable hotspots to target (infrastructure efficiency, deployment choices, workload optimization) and may shift reporting and investment from portfolio-level estimates to product-specific reduction projects, impacting cloud spend allocation and sustainability roadmaps.

Source: [SAP](https://news.sap.com/2026/11/sap-product-level-cloud-emissions-energy-data-customers/) · developing

**3. SAP Business Suite 7: ECC maintenance ends; plan history retention**
*ECC exit & S/4HANA*

SAP sets mainstream maintenance for SAP Business Suite 7 to end at the close of 2027, with optional extended maintenance to the end of 2030 at "a premium of two percentage points on the maintenance basis". The migration approach determines which closed years stay in ECC or move to the target system; ensure cleared-item links, stored currency amounts, and custom Z‑reports are captured so audit trails remain readable.

**What it changes:** You must budget and assign an owner now for retaining and reconciling retained ECC history (cleared items, stored currency amounts, Z‑reports) or risk audit, tax and dispute costs later.

Source: [ERP Today](https://erp.today/sap-ecc-retirement-what-happens-to-the-data-left-behind/) · developing

**4. SAP makes ABAP platform backbone for agentic AI**
*Clean Core & BTP*

ABAP is being positioned as the enterprise execution backbone for agentic AI, able to run governed, reliable agents inside business processes, Sonja Liénard said. SAP released the ABAP MCP server in the second quarter to open ABAP to MCP-compatible agents, is building seven migration agent families and supporting earlier releases with ABAP AI capabilities, and plans more migration tools by year-end.

**What it changes:** Expect work to shift from manual form-driven processes to agent-led automation that requires investment in ABAP platform guardrails, MCP interfaces, testing capacity and potential compute/storage upgrades during migrations.

Source: [SAP](https://news.sap.com/2026/11/abap-platform-becoming-enterprise-grade-execution-backbone-agentic-ai/) · developing

**5. SAP and VF open S.Fashion intelligent retail test store**
*Ecosystem*

SAP and VF Corporation opened S.Fashion, a retail innovation space at SAP’s Walldorf headquarters to test AI-enabled, end-to-end retail processes. The store links item-level RFID, robotics and SAP applications across inventory, orders and replenishment, operates autonomously during selected hours with no staff on site, and uses Joule to guide personalization and checkout.

**What it changes:** Expect near-term costs for RFID, robotics and integration proofs-of-concept and potential follow-on spend on BTP/AI agent integration if pilots validate lower operating complexity and labor displacement.

Source: [SAP](https://news.sap.com/2026/11/sap-and-vf-corporation-open-intelligent-fashion-store/)

## Deadline Radar

Dated SAP changes to plan around, soonest first.

- **31 Dec 2027** · Mainstream maintenance ends for BW 7.5 · *SAP BW 7.5* · in ~14 months ([source](https://www.riministreet.com/blog/sap-end-of-mainstream-maintenance-deadlines-are-looming-for-gts-bobj-bpc-bw-hybris/))
- **31 Dec 2027** · Mainstream maintenance ends for ECC 6.0 (EHP 6-8) · *SAP ECC 6.0 / Business Suite 7* · in ~14 months ([source](https://www.dvwanalytics.com/blog/sap-ecc-end-of-support-a-practical-primer))
- **31 Dec 2027** · Mainstream maintenance ends for PI/PO 7.5 · *SAP Process Orchestration 7.5* · in ~14 months ([source](https://leverx.com/en-gb/blog/sap-pi-po-to-integration-suite-migration-uk))
- **31 Dec 2030** **NEW** · End of extended maintenance · *SAP Business Suite 7* · in ~4 years ([source](https://erp.today/sap-ecc-retirement-what-happens-to-the-data-left-behind/))
- **31 Dec 2030** · Optional extended maintenance ends (2-point premium) · *SAP ECC 6.0 / Business Suite 7* · in ~4 years ([source](https://www.panorama-consulting.com/18-months-to-the-sap-ecc-cliff-and-half-of-customers-still-havent-moved/))
- **31 Dec 2030** · Optional extended maintenance ends for PI/PO 7.5 · *SAP Process Orchestration 7.5* · in ~4 years ([source](https://leverx.com/en-gb/blog/sap-pi-po-to-integration-suite-migration-uk))
- **31 Dec 2030** · SAP ends third-party database resale/support and Java support for Business Suite 7 · *SAP Business Suite 7 on third-party databases* · in ~4 years ([source](https://sapinsider.org/blogs/sap-sets-2030-cutoff-for-third-party-database-and-java-support/))
- **Dec 2033** · ERP private edition transition option ends (selected RISE customers) · *SAP ERP, private edition, transition option* · in ~7 years ([source](https://sapinsider.org/blogs/what-erp-support-deadlines-actually-mean-for-companies/))

## Sources for the Take

1. Two flaws rated 10.0, the maximum on the Common Vulnerability Scoring System (CVSS), affect the Internet Communication Manager (ICM) in SAP NetWeaver AS ABAP and SAP Web Dispatcher (CVE-2026-76964 and CVE-2026-89126). ([ERP Today](https://erp.today/sap-security-patch-day-november-2026-shared-infrastructure/))
2. The third maximum-severity flaw, which Onapsis named PROXYGATE, sits in SAP Gateway (CVE-2026-89103). ([ERP Today](https://erp.today/sap-security-patch-day-november-2026-shared-infrastructure/))
3. An unauthenticated attacker could use that to run code and take control of the system. ([ERP Today](https://erp.today/sap-security-patch-day-november-2026-shared-infrastructure/))
4. The cross-site request forgery flaw (CVE-2026-89119), rated 9.6, affects the administration interface in the Web Dispatcher and ICM and depends on an administrator’s active session. ([ERP Today](https://erp.today/sap-security-patch-day-november-2026-shared-infrastructure/))
5. The four GitHub advisories cover SAP Cloud SDK packages and a sandbox project. ([ERP Today](https://erp.today/sap-security-patch-day-november-2026-shared-infrastructure/))

---

*The SAP Signal* is curated and signed off by Sachin. Public sources only; views are my own.
