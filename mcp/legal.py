"""Legal safeguards — product disclaimers and contact constants.

These are product-level mitigations, not a substitute for counsel. Have a
licensed attorney review the API Terms of Service and Privacy Policy
(marketing/site/terms.html, marketing/site/privacy.html) before launch.

Before launch, replace CONTACT_EMAIL with a real monitored inbox and add it
to the launch checklist in marketing/launch/RUNBOOK.md.
"""

DISCLAIMER = (
    "Fineprint provides automated informational analysis only. It is not legal "
    "advice, and Fineprint is not a law firm. Verify material findings against "
    "the quoted source text and consult a licensed attorney before acting."
)

DISCLAIMER_LONG = (
    "IMPORTANT — NOT LEGAL ADVICE. This report is an automated informational "
    "assessment produced by software. It is not legal advice, does not create "
    "an attorney-client relationship, and Fineprint is not a law firm. Risk scores "
    "and pass / flag / block verdicts reflect Fineprint's automated assessment "
    "methodology as of the report date. Every finding must be verified against "
    "the verbatim quoted source text. Consult a licensed attorney before making "
    "legal or business decisions based on this report."
)

# Placeholder inbox — replace with a real monitored address before launch.
CONTACT_EMAIL = "fineprintcorp100@gmail.com"
