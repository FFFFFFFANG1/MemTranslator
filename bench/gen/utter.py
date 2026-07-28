"""UTTER: skeleton + persona card + incident hook → the sentence that enters
the episode. The generator PHYSICALLY cannot see the source sentence — its
inputs are the structured proposition, a persona voice, and the work request
the rule hangs off. Licence and anti-backbone both fall out of that wall.

Three surface forms with enforced quotas (complaint 40 / aside 35 /
standing_order ≤25): the product's _RULE_PAT regex literally contains
以后|一律|from now on|always, so a corpus of pure standing orders measures
that regex, not the system. Today's persona files are 100% standing/complaint
explicit — one reason E0 is a toy.

Also emits `clause` (short appendable form, consumed by the edited_diff
moves) and `alt_clause` (synonymous rewording, for the reword move).
"""
import json

from bench.gen.flash import flash_json

SURFACES = ("complaint", "aside", "standing_order")

SYSTEM = """You write ONE user message in a chat with their AI assistant, in the user's voice.

You get:
- PROPOSITION: a structured delivery rule the user wants to establish
- PERSONA: who the user is (language, register, quirks)
- HOOK: the work request or recent event this message hangs off
- SURFACE: how the rule comes out:
  * complaint — the user complains about the last output and the rule grows out of the complaint
  * aside — the rule is dropped mid-request, casually, while asking for the HOOK task
  * standing_order — an explicit "from now on / 以后都" instruction

Requirements:
1. The message must EXPRESS the proposition faithfully: same object, same threshold number, same polarity. Never drop or change the number.
2. Sound like a real person typing quickly in the persona's language and register. Not documentation prose.
3. For "aside": the message must ALSO contain the HOOK work request — one string doing two jobs.
4. Output exactly one JSON object:
{"utterance": "<the message>",
 "clause": "<short clause form of the rule, appendable to a request, in the persona's language>",
 "alt_clause": "<synonymous rewording of clause, different surface words>"}"""


def utter(skeleton: dict, persona_card: dict, hook: str,
          surface: str) -> dict | None:
    user = (f"PROPOSITION:\n{json.dumps(skeleton, ensure_ascii=False)}\n\n"
            f"PERSONA:\n{json.dumps(persona_card, ensure_ascii=False)}\n\n"
            f"HOOK:\n{hook}\n\nSURFACE: {surface}\n\nJSON:")
    got = flash_json(SYSTEM, user, max_tokens=600, temperature=0.7)
    if not isinstance(got, dict) or not got.get("utterance") \
            or not got.get("clause"):
        return None
    return {"utterance": got["utterance"].strip(),
            "clause": got["clause"].strip(),
            "alt_clause": (got.get("alt_clause") or got["clause"]).strip(),
            "surface": surface}
