import json
import re

def safe_json_parse(text):
    # Extract JSON from text
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except:
            pass
    # Fallback
    return {"clips": []}