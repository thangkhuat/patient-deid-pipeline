"""Boundary over-extension check for Comprehend Medical on AU mobile numbers.

Question being tested: does a real DetectPHI entity's span ever start
BEFORE or end AFTER the true phone number's actual position in the text?
(As opposed to truncation -- ending too early -- which is already
documented and understood.)

Each sentence below deliberately puts punctuation or adjacent words hard
against the number, with no buffering space -- exactly where a model
might plausibly grab one extra character it shouldn't.

Run this against the real API (requires live AWS access) and read the
printed comparison for each case.
"""

import boto3

TEST_SENTENCES = [
    # Baseline: normal spacing, for comparison against the edge cases below
    ("Please contact the patient on 0412 345 678 to confirm the appointment.", "0412 345 678"),
    # Parentheses directly against the number on both sides
    ("Emergency contact (0412 345 678) should be called if condition worsens.", "0412 345 678"),
    # Colon then dash-formatted number, period immediately after with no space
    ("Mobile: 0412-345-678. Available after 5pm.", "0412-345-678"),
    # No separator, no space before "this" after
    ("SMS reminder was sent to 0412345678 this morning.", "0412345678"),
    # International format, comma directly after with no space
    ("Alternative contact number: +61 412 345 678,spoke to daughter.", "+61 412 345 678"),
    # Comma directly attached on BOTH sides -- the most aggressive case
    ("Patient's mobile,0412 345 678,was unreachable during the visit.", "0412 345 678"),
]


def check_boundaries():
    client = boto3.client("comprehendmedical", region_name="ap-southeast-2")

    for text, phone_fragment in TEST_SENTENCES:
        true_start = text.index(phone_fragment)
        true_end = true_start + len(phone_fragment)

        response = client.detect_phi(Text=text)
        entities = response["Entities"]

        # Find whichever entity's span overlaps the true phone number position
        matches = [
            e for e in entities
            if e["BeginOffset"] < true_end and true_start < e["EndOffset"]
        ]

        print(f"Text: {text!r}")
        print(f"  True span:   [{true_start}:{true_end}]  {phone_fragment!r}")

        if not matches:
            print("  NO ENTITY FOUND OVERLAPPING THIS NUMBER (silent miss)")
            print()
            continue

        for e in matches:
            begin_diff = e["BeginOffset"] - true_start
            end_diff = e["EndOffset"] - true_end
            print(f"  Real entity: [{e['BeginOffset']}:{e['EndOffset']}]  "
                  f"Type={e['Type']}  Score={e['Score']:.3f}  Text={e['Text']!r}")
            if begin_diff < 0:
                print(f"  *** STARTS {-begin_diff} CHAR(S) EARLIER THAN TRUE START ***")
            if end_diff > 0:
                print(f"  *** ENDS {end_diff} CHAR(S) LATER THAN TRUE END ***")
            if begin_diff == 0 and end_diff <= 0:
                print(f"  OK -- entity starts at the true start, ends at or before true end "
                      f"({'exact match' if end_diff == 0 else 'truncated, known behavior'})")
        print()


if __name__ == "__main__":
    check_boundaries()