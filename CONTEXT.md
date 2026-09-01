# MemTranslator

MemTranslator is a user-side preference-memory layer that applies remembered
working preferences inside the user's existing input box.

## Desktop actions

**Write**:
The `Fn+R` action that compiles applicable preferences into the focused draft. It never sends the draft or creates learning evidence by itself.
_Avoid_: Rewrite, Polish, R hotkey

**Learn**:
The `Fn+Enter` action that forwards one ordinary Enter and explicitly submits user-authored evidence. For a matching Pending Write, it also submits attributed correction feedback.
_Avoid_: Capture, Save, Send hotkey, Enter hotkey

**Pending Write**:
A composer-bound provenance session created by Write and consumed only at a matching lifecycle boundary. It survives focus changes so leaving a composer and returning does not lose attribution.
_Avoid_: Tracker, tracking session, pending draft

**Ordinary Enter**:
An unmodified Enter handled by the target application. It may dismiss a matching Pending Write but never learns.
_Avoid_: Learn, capture

## Learning routes

**Extractor A**:
The route that derives reusable preferences from user-authored evidence submitted by Learn or the memory manager.

**Extractor B**:
The route that revises or retires preferences applied by Write using an attributed user correction.

**Correction feedback**:
The attributed difference between the latest Write result and the draft submitted by Learn. It can affect only preferences applied by that Write.
_Avoid_: observation, tracking result
