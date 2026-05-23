from ollama import generate
import json
try:
    resp = generate(model='qwen2.5-coder:1.5b', prompt='{"test": true}', options={'temperature': 0})
    print('OK:', resp)
except Exception as e:
    print('ERROR:', type(e), e)
    try:
        import traceback
        traceback.print_exc()
    except Exception:
        pass
