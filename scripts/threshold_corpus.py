"""FR-4 threshold research: what does Comprehend Medical actually do with
ambiguous or borderline text, versus text with no PHI at all?

Three categories, each testing a different part of the min_score=0 case:

1. AMBIGUOUS_REAL_PHI -- text that IS genuinely identifying, but phrased
   in a way a model might reasonably be less than fully confident about
   (informal references, non-Western names, vague ages, partial
   addresses). If these still score reasonably, that's evidence low
   scores track genuine ambiguity, not noise.

2. CLEAN_BASELINE -- unambiguous PHI, for contrast. Expected to score
   high, the way the original sample note's five non-phone entities did.

3. NO_PHI_CONTROL -- ordinary clinical language with NO identifying
   content at all. This is the category that actually tests the cost of
   min_score=0: if Comprehend Medical ever tags anything here, that's
   the real, measured false-positive risk -- not a hypothetical one.

Run against the live API (requires AWS access and bills the account --
11 DetectPHI calls) -- no guessed scores, given how wrong the hand-built
mock's guesses turned out to be earlier in this project. Not part of the
test suite; this is round 1 of the three that settled FR-4, and its
result (0 false positives across 11 sentences) is why round 2 widened the
no-PHI corpus to 60. See docs/decision-log.md, "FR-4 resolved".
"""

import boto3

AMBIGUOUS_REAL_PHI = [
    "Patient's mother, Nguyen Thi Huong, reports similar symptoms in the family.",
    "The patient, an elderly woman in her late 70s, presented with confusion.",
    "Referred by the patient's GP, Dr. K, for further assessment.",
    "Lives alone in the outer suburbs, family nearby.",
    "Son Tom drove her to the clinic this morning.",
]

CLEAN_BASELINE = [
    "Patient Maria Rodriguez, DOB 22/11/1975, residing at 45 Collins Street, Melbourne.",
    "Seen by Dr. Michael Thompson on 15/08/2026 for routine follow-up.",
]

NO_PHI_CONTROL = [
    "Patient presented with mild headache and nausea, resolving after rest.",
    "Blood pressure within normal range; no further action required.",
    "Advised to continue current medication and return if symptoms worsen.",
    "The clinic was busy this morning with several walk-in patients.",
]


def run_category(client, label, texts):
    print(f"\n{'=' * 60}\n{label}\n{'=' * 60}")
    for text in texts:
        response = client.detect_phi(Text=text)
        entities = response["Entities"]
        print(f"\nText: {text!r}")
        if not entities:
            print("  -> no entities detected")
        for e in entities:
            print(f"  -> {e['Text']!r}  Type={e['Type']}  Score={e['Score']:.4f}")


def main():
    client = boto3.client("comprehendmedical", region_name="ap-southeast-2")
    run_category(client, "1. AMBIGUOUS BUT REAL PHI", AMBIGUOUS_REAL_PHI)
    run_category(client, "2. CLEAN BASELINE", CLEAN_BASELINE)
    run_category(client, "3. NO-PHI CONTROL (false-positive check)", NO_PHI_CONTROL)

    print(f"\n{'=' * 60}\nWhat to look for\n{'=' * 60}")
    print("Category 1: do scores stay reasonably high despite phrasing")
    print("  ambiguity, or do they drop meaningfully -- and if they drop,")
    print("  is the span/type still basically correct?")
    print("Category 2: sanity check -- should score similarly to the")
    print("  original sample note's 0.995+ entities.")
    print("Category 3: the actual evidence. Any entity here at all is a")
    print("  real, measured false positive -- note its score. That")
    print("  number is the real cost of min_score=0, not a guess.")


if __name__ == "__main__":
    main()