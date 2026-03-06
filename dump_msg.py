import sys
import json
from xai_sdk.chat import user

msg = user("hello")
print(type(msg))
print(dir(msg))
try:
    print("msg.__dict__", msg.__dict__)
except Exception as e:
    pass
