

def test_retrospective_complaint_is_a_signal():
    from memtranslator.signals import screen_message
    msg = ("please draft the weekly update for the team."
           "that last draft you sent was way too heavy with exclamation "
           "marks, keep punctuation plain")
    spans = screen_message(msg, existing_keys=[], existing_texts=[])
    assert any("exclamation" in s for s in spans)


def test_short_deictic_anchor_reaches_back_two_sentences():
    from memtranslator.signals import screen_message
    msg = ("Skip trailing commas in generated config files. "
           "It keeps tripping the parser. "
           "From now on, just avoid that.。")
    spans = screen_message(msg, existing_keys=[], existing_texts=[])
    assert any("trailing" in s for s in spans)


def test_plain_chatter_still_silent():
    from memtranslator.signals import screen_message
    msg = ("can you check the deploy status of the api service. "
           "the dashboard shows two pods restarting")
    assert screen_message(msg, existing_keys=[], existing_texts=[]) == []
