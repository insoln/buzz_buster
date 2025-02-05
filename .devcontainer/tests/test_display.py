from app.formatting import display_chat,display_user

class DictObj:
    def __init__(self, in_dict:dict):
        assert isinstance(in_dict, dict)
        for key, val in in_dict.items():
            if isinstance(val, (list, tuple)):
                setattr(self, key, [DictObj(x) if isinstance(x, dict) else x for x in val])
            else:
                setattr(self, key, DictObj(val) if isinstance(val, dict) else val)

def test_display_user():
    assert display_user(DictObj({
        "id":169118642,
        "first_name":"Иван",
        "last_name":"Иванов",
        "username":"ivanov"
        })) == "#169118642 Иван Иванов (@ivanov)"
    
def test_display_chat():
    assert display_chat(DictObj({
        "id":-1002256895550,
        "title":"Test chat",
        "username":"test_chat"
        })) == "#-1002256895550 Test chat (@test_chat)"