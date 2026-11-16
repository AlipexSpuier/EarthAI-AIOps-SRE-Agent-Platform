from collections import Counter

from fastapi import FastAPI, Response

app = FastAPI()
calls = Counter()


@app.get("/{mode}/models")
async def models(mode: str, response: Response):
    calls[mode] += 1
    if mode == "failed":
        response.status_code = 503
        return {"error": "isolated catalog failure"}
    return {"data": [{"id": "first-local-model"}, {"id": "second-local-model"}]} if mode == "v1" else {"data": []}


@app.get("/checks")
async def checks():
    return dict(calls)
