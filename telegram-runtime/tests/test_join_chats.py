from runtime.account.join_chats import parse_ref


def test_parse_numeric_ids():
    assert parse_ref(-1002037802920) == ('chat_id', -1002037802920)
    assert parse_ref('-1002037802920') == ('chat_id', -1002037802920)
    assert parse_ref('777000') == ('chat_id', 777000)


def test_parse_invite_links():
    assert parse_ref('https://t.me/+BAlfo9owVslkNjRk') == ('invite', 'BAlfo9owVslkNjRk')
    assert parse_ref('t.me/+AbC_123') == ('invite', 'AbC_123')
    assert parse_ref('https://t.me/joinchat/AAAAAFE') == ('invite', 'AAAAAFE')
    assert parse_ref('tg://join?invite=BAlfo9owVslkNjRk') == ('invite', 'BAlfo9owVslkNjRk')


def test_parse_public_links_and_usernames():
    assert parse_ref('https://t.me/qunzua123') == ('username', 'qunzua123')
    assert parse_ref('t.me/qunzua123') == ('username', 'qunzua123')
    assert parse_ref('@qunzua123') == ('username', 'qunzua123')
    assert parse_ref('qunzua123') == ('username', 'qunzua123')


def test_parse_private_c_link():
    assert parse_ref('https://t.me/c/2037802920/123') == ('chat_id', -1002037802920)


def test_parse_rejects_garbage():
    for bad in ('', '  ', 'not a chat!', 't.me/', 'https://example.com/x'):
        try:
            parse_ref(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f'should reject {bad!r}')
