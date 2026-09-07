"""FR-4 threshold research, round 2: a much larger no-PHI corpus.

Round 1 (11 sentences, 0 false positives) only bounds the true
false-positive rate at ~27% (rule of three: 3/n). This corpus targets 60
no-PHI sentences specifically, to tighten that bound to ~5% if zero
false positives are observed again -- see decision-log.md discussion.

Structured into six thematic groups (10 each) rather than near-duplicate
phrasing, since a systematic false-positive pattern tied to one phrasing
style would only be caught once by near-identical sentences, not sixty
times independently.

Run against the live API (requires AWS access and bills the account --
60 DetectPHI calls). Not part of the test suite; kept as the record of
how FR-4's threshold was evidenced. Result: 1 false positive, an ADDRESS
tag on "physiotherapy department" at 0.7026, which round 3 went on to
isolate -- see docs/decision-log.md.
"""

import boto3

NUMERIC_CLINICAL_DATA = [
    "Blood pressure recorded at 120 over 80, within normal limits.",
    "Temperature 37.2 degrees, no fever noted.",
    "Prescribed 50mg twice daily for two weeks.",
    "Oxygen saturation at 98 percent on room air.",
    "Heart rate 72 beats per minute, regular rhythm.",
    "Dosage increased to 200 milligrams from next dose.",
    "Weight recorded as 68 kilograms at this visit.",
    "Room 204, bed 2, no visitors reported.",
    "Lab result glucose level 5.4 mmol/L, within range.",
    "Follow-up scheduled in three weeks' time.",
]

SYMPTOM_NARRATIVE = [
    "Complains of mild lower back pain radiating to the left leg.",
    "No signs of infection observed on examination.",
    "Patient reports improved sleep since last visit.",
    "Denies chest pain, shortness of breath, or dizziness.",
    "Mild swelling noted in the right ankle.",
    "Appetite has returned to normal over recent days.",
    "No adverse reaction to the new medication noted.",
    "Cough persists but has reduced in frequency.",
    "Skin appears clear with no rash present.",
    "Mobility has improved following physiotherapy sessions.",
]

ADMINISTRATIVE_INSTRUCTIONS = [
    "Continue current treatment plan and reassess in one month.",
    "Referral sent to the physiotherapy department.",
    "Discharge planned pending final review by the team.",
    "Nursing staff to monitor overnight for any changes.",
    "Medication chart updated to reflect the new dosage.",
    "Patient advised to rest and avoid strenuous activity.",
    "Wound dressing to be changed every second day.",
    "Vaccination administered as per standard schedule.",
    "Consent form signed prior to the procedure.",
    "Discharge summary to be sent to the general practice.",
]

RELATIVE_TIME_PHRASES = [
    "Symptoms began approximately two weeks ago.",
    "Last reviewed earlier this year with no concerns raised.",
    "Condition has been stable for several months.",
    "Due for reassessment early next quarter.",
    "Reported the issue started sometime last winter.",
    "Improvement noted within the first few days.",
    "History of similar episodes over the past year.",
    "Next appointment tentatively set for later this month.",
    "Ongoing monitoring since the initial diagnosis.",
    "No changes reported over the last fortnight.",
]

GENERIC_STAFF_ROLES = [
    "Nurses on the ward were notified of the change in condition.",
    "The on-call registrar reviewed the case overnight.",
    "Pharmacy confirmed the medication was available.",
    "Radiology reported no abnormalities on the scan.",
    "The multidisciplinary team discussed the case today.",
    "Physiotherapist recommended a graduated exercise program.",
    "Dietitian input requested for nutritional assessment.",
    "Social work was consulted regarding discharge planning.",
    "The triage nurse assessed the patient on arrival.",
    "Consultant reviewed the imaging results this afternoon.",
]

ANATOMY_AND_EXAM_TERMS = [
    "Auscultation of the chest revealed clear breath sounds.",
    "Abdomen soft and non-tender on palpation.",
    "Range of motion in the shoulder remains limited.",
    "Reflexes intact and symmetrical bilaterally.",
    "No lymphadenopathy detected on examination.",
    "Pupils equal and reactive to light.",
    "Gait steady, no assistance required for mobility.",
    "Wound edges well approximated, healing as expected.",
    "No tenderness on palpation of the lumbar spine.",
    "Capillary refill time within normal limits.",
]

ALL_GROUPS = {
    "Numeric clinical data": NUMERIC_CLINICAL_DATA,
    "Symptom narrative": SYMPTOM_NARRATIVE,
    "Administrative instructions": ADMINISTRATIVE_INSTRUCTIONS,
    "Relative time phrases": RELATIVE_TIME_PHRASES,
    "Generic staff roles": GENERIC_STAFF_ROLES,
    "Anatomy and exam terms": ANATOMY_AND_EXAM_TERMS,
}


def main():
    client = boto3.client("comprehendmedical", region_name="ap-southeast-2")

    total_sentences = 0
    total_false_positives = 0

    for group_name, sentences in ALL_GROUPS.items():
        print(f"\n{'=' * 60}\n{group_name}\n{'=' * 60}")
        for text in sentences:
            total_sentences += 1
            response = client.detect_phi(Text=text)
            entities = response["Entities"]
            if not entities:
                print(f"  OK   -- {text!r}")
            else:
                total_false_positives += len(entities)
                print(f"  FLAG -- {text!r}")
                for e in entities:
                    print(f"           -> {e['Text']!r}  Type={e['Type']}  Score={e['Score']:.4f}")

    print(f"\n{'=' * 60}\nSummary\n{'=' * 60}")
    print(f"Sentences tested: {total_sentences}")
    print(f"False positives found: {total_false_positives}")

    if total_false_positives == 0:
        upper_bound = 3 / total_sentences
        print(f"Rule-of-three 95% upper bound on true false-positive rate: {upper_bound:.1%}")
    else:
        observed_rate = total_false_positives / total_sentences
        print(f"Observed false-positive rate: {observed_rate:.1%}")
        print("(Non-zero result -- worth a proper confidence interval, e.g. Wilson score,")
        print(" rather than the rule of three, which only applies to zero-event samples.)")


if __name__ == "__main__":
    main()