# Demo plan: agent memory literature review

Status: planned recording script, not an executed demo or a performance result.
The README uses a shortened version of this same illustrative scenario. Keep
the product name as MemTranslator until a replacement is selected.

## What the demo should show

One short task request becomes a reviewable request that incorporates the
user's previously expressed research preferences. The user changes a
requirement before the downstream agent starts. That edit can later provide
feedback about the applied preference.

The example is about how the user wants research done. Do not preload facts,
paper lists, or conclusions about agent memory as preference evidence.

## Preparation

- Use a disposable demo environment with a separate memory store and no
  personal instructions, API keys, or unrelated conversations visible.
- Choose an allowlisted, supported input and verify read/write behavior.
  An allowlist entry alone does not establish compatibility.
- Use the real extraction and rewrite paths for any claim that preferences
  were learned. If using the deterministic demo mode or manually prepared
  rules, label that portion as a simulation or prepared memory.
- Capture the instructions below with **Option + Control + Enter** in the
  supported input. This gesture also forwards an ordinary Enter, so use a
  disposable conversation where sending those instructions is intended.
- Finish the learning preparation and inspect the stored preferences before
  recording the rewrite. Do not assume three captures trigger extraction:
  the current default A batch threshold is eight messages, and queue-age
  checks do not run on an independent timer. Do not duplicate evidence just
  to manufacture a learning result. Record any changed batching settings or
  explicit processing step used for the demo.

See [capture and batching behavior](design_detail.md#what-enters-memory).

## Exact scenario text

### Earlier captured instructions

Capture these as separate user instructions:

1. For literature reviews, always group papers by research question and
   method rather than summarize them one by one.
2. For each key paper in a literature review, include a link to the original
   paper and explain its core assumptions, where the method applies, and its
   limitations.
3. In literature reviews, compare methods using bullet points and finish with
   a suggested reading order.

Before recording, verify that the learned entries retain the literature-review
scope and that the comparison-format preference says to use bullet points.
The exact number of stored entries and their wording may differ after
extraction and consolidation.

### New request

```text
Help me conduct a literature review on agent memory.
```

### Illustrative rewrite

```text
Help me conduct a literature review on agent memory. Group papers by
research question and method rather than summarize them one by one. For
each key paper, link to the original paper and explain its core assumptions,
where the method applies, and its limitations. Compare methods using bullet
points and finish with a suggested reading order.
```

This is a storyboard target, not an exact-output assertion. Record the actual
rewrite. Verify that the research preferences were relevant, the original
task was preserved, and no unsupported facts or requirements were added.

### User edit

Replace the comparison-and-reading-order sentence with:

```text
From now on, use a table for method comparisons in literature reviews,
and finish with a suggested reading order.
```

This intentionally changes a previously applied format preference and states
a standing preference. It preserves the reading-order requirement. Do not
replace this with an unrelated new rule and claim B learned that new rule.

## Recording sequence

| Shot | What to show | Suggested caption |
| --- | --- | --- |
| 1 | Earlier captured instructions and the resulting, verified stored preferences | Learns how you want research done. |
| 2 | Type only the short new request in the supported input | Ask for the task, without repeating your preferences. |
| 3 | Press **⌥⌃R** and show the real rewrite in the same input; do not send yet | See your preferences before your agent does. |
| 4 | Edit the comparison format from bullet points to a table | Change the request now, right where you type. |
| 5 | Send the reviewed request when ready | You decide what gets sent. |
| 6, optional | After actual feedback processing, inspect the updated comparison preference and try another literature-review rewrite | This edit helped correct an applied preference. |

Keep the same input active while making the correction. Closing the tracker
can queue feedback, but observing an edit is not proof that the downstream
agent received the message. Capture the actual send separately if showing it.

## Checks before publication

- Preserve visible latency, or label cuts and time compression. Do not imply
  the rewritten request appeared instantly.
- Do not claim zero model cost. Manual editing of the current request needs
  no new rewrite call; extraction and feedback processing can make LLM calls.
- Do not imply edits are permanently stored immediately. B currently batches
  three attributed diffs or checks queue age on later learning activity; an
  idle wait alone does not guarantee processing.
- Include shot 6 only after verifying the applied-entry linkage, the actual
  stored update, and the later rewrite. If the update did not occur, omit the
  claimed success and retain only the demonstrated request-editing flow.
- Keep one-off exceptions distinct from durable preference changes. The
  wording “From now on” in this scenario makes the intended change explicit;
  it does not guarantee the extractor will interpret it correctly.
- If memory was prepared manually, do not present it as automatically learned.
  Do not manually fix a rule between shots and attribute the fix to B.
- No downstream paper-quality or literature-coverage claim follows from this
  demo. The demonstrated behavior is preference application and user control
  over the request.

For implementation boundaries, see
[Extractor B](design_detail.md#extractor-b-corrections-to-applied-memories)
and [batching](design_detail.md#batching-and-recovery).
