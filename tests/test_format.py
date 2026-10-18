from rcagent import format as fmt


def test_an_empty_template_or_message_is_named_not_left_blank():
    assert fmt.template_text("") == "(empty message)"
    assert fmt.template_text("  ") == "(empty message)"
    assert fmt.template_text("data TLB error interrupt") == "data TLB error interrupt"
