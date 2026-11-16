from backend import engine
from backend.main import app as app


async def local_completion(provider, model, messages):
    return {"role": "assistant", "content": "本地验收已收到角色指令和知识参考。本回复来自受控测试模型，不代表生产检查。"}


engine.model_completion = local_completion
