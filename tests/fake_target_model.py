import json
import sys


request = json.load(sys.stdin)
answer = "模型生成：4" if "2+2" in request.get("query", "") else "模型生成的测试回答"
print(json.dumps({"answer": answer, "trace": [{"tool": "fake", "status": "success"}]}, ensure_ascii=False))
