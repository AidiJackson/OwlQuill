"""Shared vocabulary constants for RP godmod detection and behavior enforcement.

Imported by:
  godmod_validator.py  — canonical godmod detector
  rp_behavior_engine.py — diagnostic adapters (detect_partner_control,
                           detect_partner_silence_severe)
"""

# Speech attribution verbs used in both pronoun-based and name-based detectors.
_SPEECH_VERBS: str = (
    r"said|replied|answered|responded|asked|told|whispered|murmured|"
    r"called|breathed|hissed|drawled|demanded|protested|agreed|admitted|"
    r"confessed|begged|pleaded|snapped|laughed|cried|sobbed|gasped|"
    r"repeated|spoke|echoed|added|continued|noted|urged|insisted|"
    r"warned|promised|argued|corrected|reminded|confirmed|declared"
)

# Inner emotional / cognitive state verbs used in inner-state detectors.
_INNER_STATE_VERBS: str = (
    r"thought|knew|realized|wondered|decided|chose|understood|believed|"
    r"hoped|feared|expected|wanted|needed|mused|reflected|considered"
)
