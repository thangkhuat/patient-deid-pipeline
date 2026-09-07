"""FR-4 threshold research, round 3: isolating the ADDRESS false-positive
pattern found in round 2 ("physiotherapy department" -> ADDRESS, 0.7026).

Structured to separate competing explanations, not just confirm the
original hit reproduces:

  A. Specialty + "department" -- does this exact shape repeat across
     different specialties, or was physiotherapy specifically unusual?
  B. Specialty alone, no institutional noun -- isolates whether the
     specialty word itself is the trigger.
  C. "department" attached to a NON-medical qualifier -- isolates
     whether "department" alone is enough, regardless of medical context.
  D. Specialty + a DIFFERENT institutional noun (unit/clinic/ward/team) --
     tests whether the pattern generalizes beyond the word "department"
     specifically.
  E. Bare generic locations, no specialty and no named institution at
     all -- a broader check unrelated to the department hypothesis.
  F. Genuine partial real-world location references -- a different
     category (real vague geography, not a generic institution name),
     kept separate so it doesn't get conflated with A-E's findings.

Run against the live API (requires AWS access and bills the account --
25 DetectPHI calls). Not part of the test suite; kept as the record
behind the decision-log entry "ADDRESS false positives on '[specialty] +
[place noun]' phrases", which states what each group actually returned.
"""

import boto3

SPECIALTY_PLUS_DEPARTMENT = [
    "Referral sent to the physiotherapy department.",
    "Referral sent to the cardiology department.",
    "Referral sent to the occupational therapy department.",
    "Patient transferred to the oncology department.",
    "Seen by the emergency department on arrival.",
    "Discharge summary sent to the radiology department.",
]

SPECIALTY_ALONE = [
    "Physiotherapy was arranged for next week.",
    "Cardiology reviewed the case this morning.",
    "Oncology will follow up in one month.",
]

NONMEDICAL_DEPARTMENT = [
    "Referral sent to the finance department.",
    "Query forwarded to the records department.",
    "Complaint escalated to the human resources department.",
]

SPECIALTY_PLUS_OTHER_INSTITUTION_WORDS = [
    "Referral sent to the physiotherapy unit.",
    "Referral sent to the physiotherapy clinic.",
    "Patient moved to the cardiology ward.",
    "Case discussed with the palliative care team.",
    "Transferred to the intensive care unit.",
    "Seen at the outpatient clinic this week.",
]

BARE_GENERIC_LOCATIONS = [
    "Waiting in reception for over an hour.",
    "Seen at the front desk on arrival.",
    "Reported to the nurses' station.",
    "Directed to the main entrance for parking.",
]

PARTIAL_REAL_GEOGRAPHY = [
    "Lives locally, within walking distance of the clinic.",
    "Travelled from interstate for the appointment.",
    "Resides in a rural area with limited transport access.",
]

ALL_GROUPS = {
    "A. Specialty + 'department'": SPECIALTY_PLUS_DEPARTMENT,
    "B. Specialty alone": SPECIALTY_ALONE,
    "C. Non-medical + 'department'": NONMEDICAL_DEPARTMENT,
    "D. Specialty + other institution words": SPECIALTY_PLUS_OTHER_INSTITUTION_WORDS,
    "E. Bare generic locations": BARE_GENERIC_LOCATIONS,
    "F. Partial real geography": PARTIAL_REAL_GEOGRAPHY,
}


def main():
    client = boto3.client("comprehendmedical", region_name="ap-southeast-2")

    for group_name, sentences in ALL_GROUPS.items():
        print(f"\n{'=' * 60}\n{group_name}\n{'=' * 60}")
        for text in sentences:
            response = client.detect_phi(Text=text)
            entities = response["Entities"]
            if not entities:
                print(f"  OK   -- {text!r}")
            else:
                print(f"  FLAG -- {text!r}")
                for e in entities:
                    print(f"           -> {e['Text']!r}  Type={e['Type']}  Score={e['Score']:.4f}")

    print(f"\n{'=' * 60}\nWhat each group's result would mean\n{'=' * 60}")
    print("A all flag, B clean       -> it's specialty + institutional noun together")
    print("A all flag, C also flags  -> 'department' alone is the trigger, not medical context")
    print("A flags, D doesn't        -> specifically 'department', not institutional nouns generally")
    print("A and D both flag         -> pattern generalizes beyond one specific word")
    print("E flags anything          -> broader than departments -- any generic institution reference")
    print("F flags anything          -> a DIFFERENT pattern (vague real geography), separate finding")


if __name__ == "__main__":
    main()