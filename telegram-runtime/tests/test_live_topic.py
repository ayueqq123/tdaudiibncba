from telethon.tl.types import MessageReplyHeader

from runtime.worker.live import _topic_id


def test_reply_thread_in_plain_group_is_not_topic():
    assert _topic_id(MessageReplyHeader(reply_to_msg_id=341, reply_to_top_id=340)) is None
    assert _topic_id(None) is None


def test_forum_topic():
    assert _topic_id(MessageReplyHeader(forum_topic=True, reply_to_msg_id=9, reply_to_top_id=5)) == 5
    assert _topic_id(MessageReplyHeader(forum_topic=True, reply_to_msg_id=5)) == 5


def test_display_name_prefers_nickname():
    from telethon.tl.types import Channel, User

    from runtime.worker.live import _display_name

    assert _display_name(User(id=1, first_name="阿杰", last_name="🔥", username="hangge520")) == "阿杰 🔥"
    assert _display_name(User(id=2, username="hangge520")) == "hangge520"
    assert _display_name(Channel(id=3, title="频道", photo=None, date=None, username="ch")) == "频道"
    assert _display_name(None) is None
