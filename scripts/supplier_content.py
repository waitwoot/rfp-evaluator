"""Content for the synthetic supplier proposals.

FICTIONAL. Greenfield City Library Service, the RFP, all four suppliers and
every reference named below are invented for an academic exercise. Any
resemblance to a real organisation is coincidental.

This module is pure data so the text can be edited without touching the
rendering code in generate_sample_pdfs.py. Prices are declared as line items
and the totals are computed at render time -- never typed by hand -- because a
price table whose rows do not add up is the first thing a marker notices.

Block types understood by the renderer:
    {"p": "paragraph text"}
    {"bullets": ["item", "item"]}
    {"table": {"cols": [...], "rows": [[...]], "widths": [...]}}
    {"pricing": True}   -- expands into the computed cost tables
"""

from __future__ import annotations

CURRENCY = "$"
CONTRACT_YEARS = 3

BUYER = {
    "name": "Greenfield City Library Service",
    "reference": "GCLS/RFP/2026/014",
    "title": "Replacement of the Library Management System",
    "summary": (
        "Greenfield City Library Service operates a central library and eleven "
        "branch libraries serving approximately 184,000 registered members. The "
        "present library management system was commissioned in 2006, is no longer "
        "supported by its original vendor, and cannot support self-service "
        "borrowing, online renewals, or consolidated reporting across branches. "
        "The Service invites proposals for a replacement covering catalogue "
        "management, membership, circulation (borrowing, returns, renewals, "
        "reservations), inter-branch transfers, overdue fines, and public search."
    ),
    "disclaimer": (
        "FICTIONAL DOCUMENT -- prepared for an academic exercise. Greenfield City "
        "Library Service, the suppliers and all references named in this document "
        "are invented. No real organisation is described."
    ),
}


SUPPLIERS: list[dict] = [
    # ------------------------------------------------------------------
    # Strong technical design + security; higher price; moderate schedule
    # ------------------------------------------------------------------
    {
        "name": "Apex Systems",
        "filename": "apex_systems_proposal.pdf",
        "tagline": "Engineered for longevity, secured by design",
        "submission_date": "2026-09-08",
        "experience_rating": 4.2,
        "timeline_months": 9,
        "pricing": {
            "one_off": [
                ("Discovery, solution design and architecture", 48_000),
                ("Platform licence, perpetual, 12 sites", 145_000),
                ("Configuration and development", 96_000),
                ("Data migration, 18 years of catalogue and member records", 62_000),
                ("Integration: RFID, payment gateway, council SSO", 28_000),
                ("Training and go-live support", 16_000),
            ],
            "annual": [
                ("Managed hosting and infrastructure", 34_000),
                ("Support and maintenance, 24x7, P1 response 1 hour", 38_000),
                ("Security monitoring and annual penetration test", 6_000),
            ],
        },
        "sections": [
            {
                "h": "1. Executive Summary and Understanding of the Requirement",
                "body": [
                    {"p":
                     "Apex Systems is pleased to respond to reference GCLS/RFP/2026/014 for the "
                     "replacement of the Greenfield City Library Service management system. We "
                     "understand that the incumbent system has been unsupported since 2019, that "
                     "eleven branches currently reconcile circulation data by overnight batch file, "
                     "and that members cannot renew a loan without attending a branch in person. "
                     "Our reading of the requirement is that the Service is not buying a like-for-like "
                     "replacement but a platform expected to remain in service for fifteen years."},
                    {"p":
                     "We have therefore proposed an architecture that is deliberately conservative in "
                     "its operational choices and modern in its technical ones. The result carries a "
                     "higher capital cost than a minimal replacement, and we make no attempt to "
                     "disguise that. We believe the difference is justified by the migration guarantee, "
                     "the security posture, and the absence of a forced re-platforming in year five."},
                    {"bullets": [
                        "Single consolidated catalogue across all twelve sites, no overnight batch reconciliation",
                        "Self-service borrowing and returns at RFID kiosks, with staff override",
                        "Public catalogue search, online renewals and reservations, on web and mobile",
                        "Full audit trail on every member and item transaction, retained for seven years",
                    ]},
                ],
            },
            {
                "h": "2. Proposed Solution and Technical Approach",
                "body": [
                    {"p":
                     "The solution is a service-oriented application deployed on a Kubernetes cluster "
                     "in two geographically separated regions, with PostgreSQL 16 in a primary-replica "
                     "configuration and automated failover. Circulation, catalogue, membership and "
                     "reporting are separate services communicating over an internal API gateway, so a "
                     "fault in reporting cannot take circulation offline. All services are stateless; "
                     "session state is held in a replicated Redis cluster."},
                    {"p":
                     "Every external interface is exposed as a documented REST API with OpenAPI 3.1 "
                     "specifications supplied to the Service at handover. Integration with the existing "
                     "3M RFID gates and self-service kiosks uses SIP2 with a compatibility shim we have "
                     "deployed at four comparable library authorities. Payments for overdue fines are "
                     "handled through a PCI DSS compliant gateway; no cardholder data touches the "
                     "library system. Staff authentication federates to the council Active Directory "
                     "via SAML 2.0 single sign-on."},
                    {"p":
                     "The platform is sized for a peak of 1,400 concurrent public catalogue sessions and "
                     "320 concurrent staff sessions, which is four times the Service's measured 2025 "
                     "peak. Load testing evidence against these figures will be supplied before user "
                     "acceptance testing begins. The system is designed to a recovery time objective of "
                     "four hours and a recovery point objective of fifteen minutes."},
                    {"bullets": [
                        "Kubernetes across two regions with automated failover; RTO 4 hours, RPO 15 minutes",
                        "PostgreSQL 16 primary-replica; point-in-time recovery to any second in the last 35 days",
                        "SIP2 and REST integration with existing RFID gates, kiosks and payment gateway",
                        "SAML 2.0 single sign-on against council Active Directory",
                        "OpenAPI 3.1 specifications and full source documentation delivered at handover",
                    ]},
                ],
            },
            {
                "h": "3. Implementation Plan, Team and Milestones",
                "body": [
                    {"p":
                     "We propose a nine month programme. This is longer than some respondents will "
                     "offer. The additional time is concentrated in migration and parallel running: "
                     "eighteen years of catalogue and member data cannot be moved safely in a single "
                     "weekend cutover, and we will not propose one."},
                    {"table": {
                        "cols": ["Phase", "Weeks", "Key deliverable", "Lead role"],
                        "widths": [95, 38, 200, 90],
                        "rows": [
                            ["1. Discovery and design", "1-6", "Solution design document, signed off", "Solution Architect"],
                            ["2. Build and configure", "7-20", "Configured platform in test environment", "Technical Lead"],
                            ["3. Data migration trials", "14-26", "Three full migration rehearsals with reconciliation reports", "Data Migration Lead"],
                            ["4. Integration and testing", "21-30", "RFID, payments and SSO integrated and tested", "Integration Engineer"],
                            ["5. User acceptance testing", "31-34", "UAT sign-off by Service, defect log cleared", "Test Manager"],
                            ["6. Parallel running", "35-38", "Four weeks live alongside incumbent system", "Project Manager"],
                            ["7. Cutover and hypercare", "39-40", "Go-live, 4 weeks on-site hypercare", "Project Manager"],
                        ],
                    }},
                    {"p":
                     "The core team is eight people: a Project Manager (0.6 FTE), Solution Architect "
                     "(0.5 FTE), Technical Lead (1.0 FTE), two Developers (2.0 FTE), Data Migration "
                     "Lead (0.8 FTE), Integration Engineer (0.5 FTE) and Test Manager (0.6 FTE). Named "
                     "CVs are provided in Annex A. We commit contractually to the named Solution "
                     "Architect and Data Migration Lead remaining on the engagement to go-live."},
                ],
            },
            {
                "h": "4. Commercial Proposal",
                "body": [
                    {"p":
                     "Pricing is fixed-price for the implementation, with recurring charges held flat "
                     "for the initial three year term and capped at CPI thereafter."},
                    {"pricing": True},
                    {"p": "Commercial assumptions:"},
                    {"bullets": [
                        "The Service provides a single point of contact empowered to sign off each phase",
                        "Existing RFID gates and kiosks remain in place and are SIP2 capable",
                        "Legacy data is made available in a readable export within four weeks of contract signature",
                        "Prices exclude applicable sales tax and are valid for 90 days from submission",
                        "Perpetual licence: the Service retains the right to use the platform if support lapses",
                    ]},
                ],
            },
            {
                "h": "5. Security, Compliance and Risk Controls",
                "body": [
                    {"p":
                     "Apex Systems holds ISO 27001:2022 certification, most recently audited in March "
                     "2026, and completes an annual SOC 2 Type II examination. Certificates and the "
                     "most recent SOC 2 report are available under NDA on request."},
                    {"p":
                     "Member data is encrypted at rest using AES-256 and in transit using TLS 1.3. "
                     "Access is governed by role-based access control with eleven predefined library "
                     "roles; every privileged action writes an immutable audit record capturing actor, "
                     "timestamp, and the before and after state of the record. Borrowing history is "
                     "pseudonymised after the retention period configured by the Service, defaulting "
                     "to two years, in recognition of the particular sensitivity of library borrowing "
                     "records. Data is held exclusively in-country; no member data is processed outside "
                     "the jurisdiction."},
                    {"p":
                     "An independent CREST-accredited penetration test is performed before go-live and "
                     "annually thereafter, with the executive summary shared with the Service and all "
                     "high or critical findings remediated within 30 days. We maintain a documented "
                     "incident response procedure with a 24 hour breach notification commitment to the "
                     "Service."},
                    {"table": {
                        "cols": ["Risk", "Likelihood", "Mitigation"],
                        "widths": [140, 70, 213],
                        "rows": [
                            ["Legacy data quality worse than expected", "High",
                             "Three migration rehearsals; reconciliation report signed off before each"],
                            ["RFID kiosks not SIP2 compliant", "Medium",
                             "Compatibility assessed in week 2 of discovery; shim already proven at 4 sites"],
                            ["Staff resistance to new workflow", "Medium",
                             "Branch champions trained in phase 5; four weeks parallel running"],
                            ["Key personnel loss", "Low",
                             "Contractual commitment to named architect and migration lead"],
                        ],
                    }},
                ],
            },
            {
                "h": "6. Support Model, Experience and References",
                "body": [
                    {"p":
                     "Support is 24x7 for priority 1 incidents with a one hour response target and a "
                     "four hour resolution target, and business hours for priority 3 and 4. A named "
                     "service delivery manager holds a monthly service review with the Service. Service "
                     "credits apply against the annual support charge where targets are missed in two "
                     "consecutive months."},
                    {"p":
                     "Apex Systems was founded in 2009 and employs 240 staff. We have delivered library "
                     "and archive systems to seven public sector clients. Two comparable references:"},
                    {"bullets": [
                        "Northgate Borough Libraries, 9 branches, 110,000 members, delivered 2023, "
                        "migrated 14 years of circulation history with zero reconciliation variance",
                        "Weston County Archive Service, 4 sites, delivered 2024, ISO 27001 aligned "
                        "deployment with council SSO federation",
                    ]},
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Lowest price, fast timeline; weak compliance detail; limited experience
    # ------------------------------------------------------------------
    {
        "name": "BrightPath Tech",
        "filename": "brightpath_tech_proposal.pdf",
        "tagline": "Live in sixteen weeks",
        "submission_date": "2026-09-11",
        "experience_rating": 2.5,
        "timeline_months": 4,
        "pricing": {
            "one_off": [
                ("Solution setup and configuration", 34_000),
                ("Subscription onboarding", 22_000),
                ("Development and customisation", 58_000),
                ("Data migration, standard import", 38_000),
                ("Integration services", 22_000),
                ("Training, 2 days remote", 12_000),
            ],
            "annual": [
                ("SaaS subscription, 12 sites", 24_000),
                ("Support, business hours, email", 10_000),
            ],
        },
        "sections": [
            {
                "h": "1. Executive Summary and Understanding of the Requirement",
                "body": [
                    {"p":
                     "BrightPath Tech offers Greenfield City Library Service the fastest and lowest "
                     "cost route off its unsupported 2006 system. We can have the Service live on a "
                     "modern cloud platform in sixteen weeks at a total three year cost substantially "
                     "below any custom build. We understand the Service needs catalogue, membership, "
                     "circulation, reservations, inter-branch transfers, fines and public search."},
                    {"p":
                     "Our position is straightforward: every month the current system remains in "
                     "service is a month of operational risk on software no vendor will patch. We "
                     "prioritise getting the Service onto supported software quickly, then improving "
                     "from there. Our platform is already built. The Service is configuring a product, "
                     "not funding a development programme."},
                    {"bullets": [
                        "Sixteen weeks from contract signature to go-live",
                        "Lowest total three year cost of ownership of any realistic option",
                        "No capital licence -- a single predictable annual subscription",
                        "Product roadmap improvements included at no extra charge",
                    ]},
                ],
            },
            {
                "h": "2. Proposed Solution and Technical Approach",
                "body": [
                    {"p":
                     "BrightPath Library Cloud is a multi-tenant SaaS application hosted on a major "
                     "public cloud provider. The Service receives a configured tenant rather than a "
                     "bespoke deployment. Configuration covers branch structure, loan rules, fine "
                     "tariffs, membership categories and catalogue fields. The public search interface "
                     "is responsive and works on mobile without a separate app."},
                    {"p":
                     "Integration with the existing RFID kiosks is achieved through our standard SIP2 "
                     "connector. Payment for fines uses our built-in payment module. Staff log in with "
                     "username and password; single sign-on against the council directory is on our "
                     "roadmap for 2027 and can be discussed."},
                    {"p":
                     "Because the platform is multi-tenant, the Service benefits from every improvement "
                     "we ship to all customers. The corresponding constraint, which we state plainly, "
                     "is that customisations outside our configuration options are not generally "
                     "available, and workflows unique to the Service may need to be adapted to the "
                     "product rather than the reverse."},
                    {"bullets": [
                        "Multi-tenant SaaS; no infrastructure for the Service to run",
                        "Standard SIP2 connector for existing RFID kiosks",
                        "Built-in fines payment module",
                        "Single sign-on not available at launch; roadmap item for 2027",
                    ]},
                ],
            },
            {
                "h": "3. Implementation Plan, Team and Milestones",
                "body": [
                    {"p":
                     "Sixteen weeks, four phases. The plan assumes the Service can make configuration "
                     "decisions within five working days of each request."},
                    {"table": {
                        "cols": ["Phase", "Weeks", "Key deliverable", "Lead role"],
                        "widths": [95, 38, 200, 90],
                        "rows": [
                            ["1. Kick-off and configuration", "1-4", "Tenant configured to agreed rules", "Implementation Consultant"],
                            ["2. Data import", "5-9", "Catalogue and member data imported", "Implementation Consultant"],
                            ["3. Integration and training", "10-13", "SIP2 connector live, staff trained remotely", "Technical Consultant"],
                            ["4. Go-live", "14-16", "Cutover weekend, 1 week remote support", "Implementation Consultant"],
                        ],
                    }},
                    {"p":
                     "The team is three people: an Implementation Consultant (1.0 FTE), a Technical "
                     "Consultant (0.5 FTE) and a part-time Account Manager. Data migration is performed "
                     "using our standard import tool; the Service is responsible for cleansing and "
                     "supplying data in our published CSV template, and for verifying the imported "
                     "records. One import rehearsal is included; additional rehearsals are chargeable "
                     "at day rate."},
                ],
            },
            {
                "h": "4. Commercial Proposal",
                "body": [
                    {"p":
                     "Our pricing is the lowest in this competition and we are confident it will remain "
                     "so. There is no perpetual licence; the subscription includes all platform updates."},
                    {"pricing": True},
                    {"p": "Commercial assumptions:"},
                    {"bullets": [
                        "Data supplied by the Service in our published CSV template, already cleansed",
                        "One data import rehearsal included; further rehearsals charged at day rate",
                        "Training delivered remotely; on-site training available at additional cost",
                        "Existing kiosks are SIP2 compliant without modification",
                        "Prices exclude applicable sales tax",
                    ]},
                ],
            },
            {
                "h": "5. Security, Compliance and Risk Controls",
                "body": [
                    {"p":
                     "Security is taken seriously at BrightPath Tech. Our platform is hosted with a "
                     "major cloud provider whose data centres carry industry-leading certifications, "
                     "and we follow industry best practice throughout our development lifecycle. Data "
                     "is encrypted and access is controlled."},
                    {"p":
                     "We are a young company and have not yet completed formal certification ourselves; "
                     "an ISO 27001 programme is planned. We are happy to complete the Service's own "
                     "security questionnaire during contract negotiation and to discuss any specific "
                     "requirements the Service may have around data handling and retention."},
                    {"table": {
                        "cols": ["Risk", "Likelihood", "Mitigation"],
                        "widths": [140, 70, 213],
                        "rows": [
                            ["Data not supplied in required template", "Medium", "Template published at kick-off"],
                            ["Configuration decisions delayed", "Medium", "Weekly checkpoint call"],
                        ],
                    }},
                ],
            },
            {
                "h": "6. Support Model, Experience and References",
                "body": [
                    {"p":
                     "Support is provided by email and web portal during business hours, 09:00 to 17:00 "
                     "Monday to Friday, with a target response of one business day. Out-of-hours cover "
                     "is not included in the standard subscription. There is no named service delivery "
                     "manager at this contract value; our support team operates a shared queue."},
                    {"p":
                     "BrightPath Tech was founded in 2023 and employs 18 staff. This would be our "
                     "largest deployment to date and our first in the public library sector. Our "
                     "comparable experience:"},
                    {"bullets": [
                        "Hallow Community Trust, 2 sites, membership and room booking, delivered 2025",
                        "Tidemark Learning Centre, single site, catalogue and lending, delivered 2024",
                    ]},
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Balanced; strongest implementation plan and support model
    # ------------------------------------------------------------------
    {
        "name": "NexaWorks",
        "filename": "nexaworks_proposal.pdf",
        "tagline": "Delivered properly, supported permanently",
        "submission_date": "2026-09-09",
        "experience_rating": 4.0,
        "timeline_months": 7,
        "pricing": {
            "one_off": [
                ("Discovery and requirements workshops", 38_000),
                ("Platform configuration", 84_000),
                ("Development and customisation", 72_000),
                ("Data migration and reconciliation", 54_000),
                ("Integration: RFID, payments, SSO, e-resources", 40_000),
                ("Training, documentation and hypercare", 24_000),
            ],
            "annual": [
                ("Cloud hosting", 26_000),
                ("Support and maintenance, extended hours", 24_000),
                ("Continuous improvement pool, 80 hours", 8_000),
            ],
        },
        "sections": [
            {
                "h": "1. Executive Summary and Understanding of the Requirement",
                "body": [
                    {"p":
                     "NexaWorks proposes a seven month delivery of a replacement library management "
                     "system for Greenfield City Library Service, followed by a support relationship "
                     "designed to last the life of the platform. We have read the requirement as three "
                     "problems rather than one: the Service must leave an unsupported system, it must "
                     "give members self-service, and it must stop reconciling eleven branches by "
                     "overnight batch."},
                    {"p":
                     "Our proposal is deliberately balanced. We are not the cheapest respondent and we "
                     "have not proposed the shortest timeline. What we have concentrated on is the part "
                     "of this programme that most commonly fails: the transition itself, and the twelve "
                     "months after go-live when branch staff are learning a new system while serving "
                     "the public."},
                    {"bullets": [
                        "Seven month delivery with a staged branch rollout, not a single big-bang cutover",
                        "Two pilot branches live eight weeks before the remaining ten",
                        "Twelve weeks of post-go-live hypercare with on-site presence in the first four",
                        "80 hours per year of included change, so small improvements never need a change request",
                    ]},
                ],
            },
            {
                "h": "2. Proposed Solution and Technical Approach",
                "body": [
                    {"p":
                     "The platform is a cloud-hosted application built on our established library "
                     "product, configured and extended for the Service. It runs on managed container "
                     "infrastructure with a managed PostgreSQL database, automated daily backups with "
                     "35 day retention, and a tested restore procedure exercised quarterly."},
                    {"p":
                     "Circulation, catalogue, membership, reservations and inter-branch transfers are "
                     "delivered as configured modules. Public search is delivered as a responsive web "
                     "interface with WCAG 2.2 AA accessibility conformance, which we consider "
                     "non-negotiable for a public library service and have priced accordingly. "
                     "Integration covers the existing RFID gates and kiosks over SIP2, the council "
                     "payment gateway for fines, SAML single sign-on for staff, and OpenAthens for the "
                     "Service's subscribed e-resources."},
                    {"p":
                     "Reporting is delivered as a set of twenty predefined operational reports agreed "
                     "during discovery, plus a self-service query builder for branch managers. All "
                     "reports draw from a read replica, so reporting load cannot affect circulation "
                     "performance at the counter."},
                    {"bullets": [
                        "Managed containers and managed PostgreSQL; daily backups, 35 day retention, quarterly restore tests",
                        "WCAG 2.2 AA conformance on the public interface, independently audited before go-live",
                        "SIP2, payment gateway, SAML single sign-on and OpenAthens integrations all in scope",
                        "Reporting from a read replica so it cannot slow down the issue desk",
                    ]},
                ],
            },
            {
                "h": "3. Implementation Plan, Team and Milestones",
                "body": [
                    {"p":
                     "Seven months, seven phases, with a staged rollout. Two pilot branches go live in "
                     "week 20; the remaining ten follow in three waves once the pilot has run a full "
                     "month including an end-of-month fines cycle. Every phase has a defined exit "
                     "criterion signed by a named person on both sides; no phase begins before the "
                     "previous one is signed off."},
                    {"table": {
                        "cols": ["Phase", "Weeks", "Exit criterion", "Accountable"],
                        "widths": [95, 38, 200, 90],
                        "rows": [
                            ["1. Discovery", "1-4", "Requirements catalogue and loan rules signed off", "Business Analyst"],
                            ["2. Configuration", "5-12", "Configured system demonstrated to branch champions", "Implementation Lead"],
                            ["3. Migration build", "7-16", "Two rehearsals complete, variance under 0.1%", "Data Lead"],
                            ["4. Integration", "11-18", "SIP2, payments, SSO and OpenAthens tested end to end", "Integration Lead"],
                            ["5. UAT and training", "17-19", "UAT signed off; 46 staff trained across 12 sites", "Test and Training Lead"],
                            ["6. Pilot go-live", "20-24", "2 pilot branches live through a full month-end", "Project Manager"],
                            ["7. Full rollout", "25-30", "All 12 sites live; 12 weeks hypercare begins", "Project Manager"],
                        ],
                    }},
                    {"p":
                     "The team is nine people with a named individual accountable for each phase exit. "
                     "A RACI matrix covering all 38 programme activities is provided in Annex B and "
                     "forms part of the contract. Governance is a weekly delivery call, a fortnightly "
                     "steering group, and a single shared risk register reviewed at every steering "
                     "group with joint ownership of every open risk."},
                    {"p":
                     "We hold a two week contingency buffer between phase 6 and phase 7, unallocated "
                     "and visible in the plan. If the pilot surfaces problems we absorb them there "
                     "rather than compressing training or testing later."},
                ],
            },
            {
                "h": "4. Commercial Proposal",
                "body": [
                    {"p":
                     "Fixed price for implementation. The annual charge includes an 80 hour continuous "
                     "improvement pool so routine small changes do not require a commercial "
                     "conversation."},
                    {"pricing": True},
                    {"p": "Commercial assumptions:"},
                    {"bullets": [
                        "Two named Service staff available two days per week during discovery and UAT",
                        "Branch champions released for two days of training each",
                        "Legacy extract supplied within six weeks of contract signature",
                        "Unused continuous improvement hours do not roll over between years",
                        "Prices exclude applicable sales tax and are valid for 120 days",
                    ]},
                ],
            },
            {
                "h": "5. Security, Compliance and Risk Controls",
                "body": [
                    {"p":
                     "NexaWorks holds ISO 27001 certification and operates a documented secure "
                     "development lifecycle including peer review, dependency scanning and static "
                     "analysis on every change. Member data is encrypted at rest and in transit using "
                     "TLS 1.2 or above. Role-based access control is configured to the Service's own "
                     "role structure during discovery, and all administrative actions are logged to an "
                     "append-only audit table."},
                    {"p":
                     "An independent penetration test is carried out before pilot go-live and the "
                     "report shared with the Service. Data is held in-country. We support the Service's "
                     "retention policy for borrowing history, with a configurable pseudonymisation "
                     "period, and provide a subject access request export tool so member requests can "
                     "be answered by library staff without a call to support."},
                    {"table": {
                        "cols": ["Risk", "Likelihood", "Mitigation"],
                        "widths": [140, 70, 213],
                        "rows": [
                            ["Pilot reveals workflow gaps", "High",
                             "Two week contingency buffer held between pilot and full rollout"],
                            ["Legacy member records duplicated", "High",
                             "De-duplication report produced at rehearsal 1; Service adjudicates before rehearsal 2"],
                            ["Branch staff under-trained at go-live", "Medium",
                             "Branch champion model; 12 weeks hypercare, on-site for the first 4"],
                            ["Month-end fines cycle behaves unexpectedly", "Medium",
                             "Pilot deliberately runs through a full month-end before wider rollout"],
                        ],
                    }},
                ],
            },
            {
                "h": "6. Support Model, Experience and References",
                "body": [
                    {"p":
                     "Support runs 07:00 to 19:00 Monday to Saturday, matching library opening hours "
                     "rather than office hours, with on-call cover for priority 1 incidents outside "
                     "those times. Response targets are 30 minutes for priority 1, two hours for "
                     "priority 2, and one business day for priority 3. Resolution targets are four "
                     "hours, one business day and ten business days respectively. Service credits are "
                     "defined in the draft service agreement at Annex C."},
                    {"p":
                     "Every customer has a named Service Delivery Manager and a named technical "
                     "escalation contact. Reviews are monthly for the first year and quarterly "
                     "thereafter. A joint improvement backlog is maintained and prioritised by the "
                     "Service at each review; the 80 hour pool is drawn from it."},
                    {"p":
                     "NexaWorks was founded in 2012 and employs 165 staff, 40 of them in the library "
                     "and cultural services practice. References:"},
                    {"bullets": [
                        "Ashford Vale Libraries, 14 branches, 205,000 members, delivered 2024, staged "
                        "rollout across four waves with no unplanned downtime at any branch",
                        "Kestrel District Council, 6 branches, delivered 2022, still supported by the "
                        "same service delivery manager",
                        "Port Ellis Library Trust, 3 sites, delivered 2021, migrated from the same "
                        "2006-era product family the Service currently operates",
                    ]},
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Strong experience + references; vague integration plan; medium pricing
    # ------------------------------------------------------------------
    {
        "name": "Orbit Digital",
        "filename": "orbit_digital_proposal.pdf",
        "tagline": "Thirty years in public libraries",
        "submission_date": "2026-09-10",
        "experience_rating": 4.6,
        "timeline_months": 8,
        "pricing": {
            "one_off": [
                ("Project initiation and design", 30_000),
                ("Licence and platform setup", 96_000),
                ("Development and customisation", 64_000),
                ("Data migration", 48_000),
                ("Integration services", 18_000),
                ("Training and change management", 12_000),
            ],
            "annual": [
                ("Hosting", 28_000),
                ("Support and maintenance", 30_000),
                ("Account management", 4_000),
            ],
        },
        "sections": [
            {
                "h": "1. Executive Summary and Understanding of the Requirement",
                "body": [
                    {"p":
                     "Orbit Digital has worked with public library services since 1996. In that time we "
                     "have replaced 61 library management systems, including nineteen migrations from "
                     "the product family Greenfield City Library Service currently operates. We know "
                     "what the Service is dealing with, because we have dealt with it before."},
                    {"p":
                     "We understand the requirement as set out in GCLS/RFP/2026/014: catalogue, "
                     "membership, circulation, reservations, inter-branch transfers, fines and public "
                     "search across twelve sites and 184,000 members. Our proposal reflects three "
                     "decades of pattern recognition about how these programmes succeed and, more "
                     "usefully, how they fail."},
                    {"bullets": [
                        "61 library management system replacements since 1996",
                        "19 prior migrations from the Service's current product family",
                        "Dedicated public libraries practice, 55 staff, not a general IT team",
                        "Reference sites available for visits, including two within 40 miles",
                    ]},
                ],
            },
            {
                "h": "2. Proposed Solution and Technical Approach",
                "body": [
                    {"p":
                     "Orbit Library Platform is a mature product, currently on version 11, used by 61 "
                     "library services. It covers catalogue management to MARC 21 and RDA standards, "
                     "membership, circulation, reservations and inter-branch transfer, fines and "
                     "charges, acquisitions, serials, and a public discovery interface. The functional "
                     "coverage required by the Service is met by the product as it stands, with "
                     "configuration rather than development."},
                    {"p":
                     "The platform is deployed on cloud infrastructure managed by Orbit Digital. "
                     "Capacity is sized from our experience of comparable services; a detailed sizing "
                     "exercise forms part of project initiation."},
                    {"p":
                     "On integration, our approach is to establish the appropriate mechanism during the "
                     "design phase. We have extensive experience of connecting to RFID equipment, "
                     "payment providers and authentication systems across our client base, and we will "
                     "work with the Service and its incumbent suppliers to agree and implement suitable "
                     "interfaces. The specific technical approach will depend on the configuration of "
                     "the existing estate, which we would expect to survey during initiation. Our "
                     "integration services line in the commercial section carries an allowance for this "
                     "work based on typical requirements at services of comparable size."},
                    {"bullets": [
                        "Mature product at version 11, in service at 61 library authorities",
                        "MARC 21 and RDA compliant cataloguing",
                        "Functional requirements met by configuration rather than development",
                        "Integration mechanisms to be determined during the design phase following a survey of the existing estate",
                    ]},
                ],
            },
            {
                "h": "3. Implementation Plan, Team and Milestones",
                "body": [
                    {"p":
                     "Eight months, following our standard implementation methodology refined across "
                     "61 deployments."},
                    {"table": {
                        "cols": ["Phase", "Weeks", "Key deliverable", "Lead role"],
                        "widths": [95, 38, 200, 90],
                        "rows": [
                            ["1. Initiation", "1-5", "Project plan, estate survey, sizing", "Project Manager"],
                            ["2. Design and configuration", "6-16", "Configured platform, design document", "Principal Consultant"],
                            ["3. Data migration", "12-24", "Migrated catalogue and member data", "Migration Specialist"],
                            ["4. Integration", "17-26", "Interfaces implemented per design", "Technical Consultant"],
                            ["5. Testing and training", "27-31", "UAT complete, 46 staff trained on site", "Training Manager"],
                            ["6. Go-live and support", "32-35", "Cutover, 3 weeks on-site support", "Project Manager"],
                        ],
                    }},
                    {"p":
                     "The team comprises a Project Manager, Principal Consultant, Migration Specialist, "
                     "Technical Consultant and Training Manager, drawn from our public libraries "
                     "practice. All five have worked on at least eight prior library replacements. "
                     "Training is delivered on site at each branch, which our experience shows produces "
                     "materially better adoption than remote delivery."},
                ],
            },
            {
                "h": "4. Commercial Proposal",
                "body": [
                    {"p":
                     "Our pricing sits mid-range for this competition and reflects a mature product "
                     "with a long support history rather than a development programme."},
                    {"pricing": True},
                    {"p": "Commercial assumptions:"},
                    {"bullets": [
                        "Integration services are provided against an allowance; work exceeding the "
                        "allowance following the estate survey is charged at day rate",
                        "Training delivered on site at all twelve branches, included",
                        "Legacy data supplied in any readable format; we will handle transformation",
                        "Annual charges subject to CPI review from year four",
                        "Prices exclude applicable sales tax",
                    ]},
                ],
            },
            {
                "h": "5. Security, Compliance and Risk Controls",
                "body": [
                    {"p":
                     "Orbit Digital holds ISO 27001 and ISO 9001 certification, both audited within the "
                     "last twelve months. Member data is encrypted at rest and in transit, held "
                     "in-country, and access is controlled through role-based permissions aligned to "
                     "library job roles. Audit logging covers member record changes, fine waivers and "
                     "privileged administrative actions."},
                    {"p":
                     "We carry out an annual penetration test of the platform and share the summary "
                     "with clients. Our data processing terms, retention schedule and breach "
                     "notification procedure are provided in Annex D and have been accepted without "
                     "amendment by 58 public sector clients."},
                    {"table": {
                        "cols": ["Risk", "Likelihood", "Mitigation"],
                        "widths": [140, 70, 213],
                        "rows": [
                            ["Integration scope larger than allowance", "Medium",
                             "Estate survey in phase 1; variation agreed before work proceeds"],
                            ["Legacy data anomalies", "Low",
                             "19 prior migrations from this product family; known anomalies catalogued"],
                            ["Branch staff availability for training", "Medium",
                             "On-site delivery scheduled around branch rotas"],
                        ],
                    }},
                ],
            },
            {
                "h": "6. Support Model, Experience and References",
                "body": [
                    {"p":
                     "Support is provided 08:00 to 18:00 Monday to Friday by our UK-based library "
                     "support desk, staffed by people who have worked in libraries. Priority 1 response "
                     "is one hour. A named account manager is assigned to the Service and meets "
                     "quarterly. Out-of-hours support is available as a chargeable option."},
                    {"p":
                     "Orbit Digital employs 310 staff, 55 of them in the public libraries practice. Our "
                     "average client relationship is 11 years and our client retention rate over the "
                     "past decade is 94 per cent. References, all of whom have agreed to site visits:"},
                    {"bullets": [
                        "Marlow District Libraries, 16 branches, 240,000 members, delivered 2023, "
                        "migrated from the same product family as the Service, 40 miles from Greenfield",
                        "Calder Heath Library Service, 11 branches, delivered 2021, client since 2004",
                        "Stanmore Unitary Authority, 9 branches, delivered 2020, client since 1999",
                        "Brookvale Libraries, 7 branches, delivered 2019, client since 2011",
                    ]},
                ],
            },
        ],
    },
]


def contract_total(pricing: dict, years: int = CONTRACT_YEARS) -> dict:
    """Compute the cost totals. Never hand-type these figures."""
    one_off = sum(amount for _, amount in pricing["one_off"])
    annual = sum(amount for _, amount in pricing["annual"])
    return {
        "one_off": one_off,
        "annual": annual,
        "years": years,
        "recurring_total": annual * years,
        "tco": one_off + annual * years,
    }


def money(amount: float) -> str:
    return f"{CURRENCY}{amount:,.0f}"
