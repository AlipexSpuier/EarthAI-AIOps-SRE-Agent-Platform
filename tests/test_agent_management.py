import pytest
from fastapi.testclient import TestClient

from backend import engine, store
from backend.main import app, login_attempts


@pytest.fixture
def client():
    login_attempts.clear()
    with TestClient(app) as client:
        response = client.post('/api/auth/register', json={'email':store.uid()+'@agents.example','password':'Agent-Features-2026!','name':'Feature Test'})
        assert response.status_code == 200
        yield client, response.json()


def create_remote(client, name='Remote Web Agent'):
    response = client.post('/api/agents', json={'kind':'remote','name':name,'url':'https://example.com/agent?space=demo#chat','description':'外部智能体入口'})
    assert response.status_code == 200, response.text
    return response.json()


def test_remote_agent_crud_and_execution_boundary(client):
    http, user = client
    remote = create_remote(http)
    assert remote['kind'] == 'remote' and remote['url'].endswith('#chat')
    assert http.post('/api/conversations',json={'agent_id':remote['id']}).status_code == 422
    assert http.post('/api/schedules',json={'name':'bad','prompt':'check','agent_id':remote['id']}).status_code == 422
    assert http.patch('/api/preferences/chat',json={'agent_id':remote['id']}).status_code == 422
    conversation = store.save_entity(user['id'],'conversations',{'title':'defense','agent_id':remote['id']})
    with pytest.raises(ValueError,match='远程'):
        engine.create_run(user['id'],conversation,'do not execute')
    with pytest.raises(ValueError,match='远程'):
        engine.trigger_schedule(user['id'],{'id':'manual','name':'bad','prompt':'x','agent_id':remote['id']})
    updated = http.patch('/api/agents/'+remote['id'],json={'kind':'local','system_prompt':'safe local'}).json()
    assert updated['kind']=='local' and updated['url']==''


@pytest.mark.parametrize('url',['javascript:alert(1)','data:text/html,test','file:///etc/passwd','https://user:password@example.com','https://example.com/ bad','https://example.com:invalid','https://example.com\\@evil.example'])
def test_remote_url_rejects_executable_or_credential_urls(client,url):
    http,_=client
    assert http.post('/api/agents',json={'kind':'remote','name':'invalid','url':url}).status_code==422


def test_agent_order_is_saved_not_newest_first_and_new_items_append(client):
    http,user=client
    original=http.get('/api/agents').json()
    first=create_remote(http,'Remote A')
    second=create_remote(http,'Remote B')
    ids=[item['id'] for item in http.get('/api/agents').json()]
    assert ids==[item['id'] for item in original]+[first['id'],second['id']]
    custom=[second['id'],*ids[:-1]]
    assert [item['id'] for item in http.post('/api/agents/reorder',json={'agent_ids':custom}).json()]==custom
    assert [item['id'] for item in store.list_entities(user['id'],'agents')]==custom
    assert http.patch('/api/agents/'+first['id'],json={'name':'Edited A','sort_order':0}).status_code==200
    assert [item['id'] for item in http.get('/api/agents').json()]==custom
    third=create_remote(http,'Remote C')
    assert [item['id'] for item in http.get('/api/agents').json()]==custom+[third['id']]
    assert http.post('/api/agents/reorder',json={'agent_ids':[third['id']]}).status_code==422
    assert http.post('/api/agents/reorder',json={'agent_ids':custom+[third['id'],third['id']]}).status_code==422
    with store.connect() as db:
        foreign=store.uid()
        db.execute('INSERT INTO users VALUES (?,?,?,?,?)',(foreign,foreign+'@test.example','unused','{}',store.now()))
    other=store.save_entity(foreign,'agents',{'name':'other'})
    assert http.post('/api/agents/reorder',json={'agent_ids':custom+[other['id']]}).status_code==422
    assert [item['id'] for item in http.get('/api/agents').json()]==custom+[third['id']]


def test_legacy_agents_stay_local_and_oldest_first(client):
    http,user=client
    before=http.get('/api/agents').json()
    a=store.save_entity(user['id'],'agents',{'name':'Legacy A','skill_ids':[],'knowledge_ids':[],'control_level':'observe'})
    b=store.save_entity(user['id'],'agents',{'name':'Legacy B','skill_ids':[],'knowledge_ids':[],'control_level':'observe'})
    data=http.get('/api/agents').json()
    assert [x['id'] for x in data]==[x['id'] for x in before]+[a['id'],b['id']]
    assert next(x for x in data if x['id']==a['id'])['kind']=='local'


def test_remote_conversion_cleans_persisted_preferences(client):
    http,user=client
    agent=http.post('/api/agents',json={'name':'可转换的个人助手','system_prompt':'仅分析','kind':'local'}).json()
    assert http.patch('/api/preferences/chat',json={'agent_id':agent['id']}).status_code==200
    assert http.patch('/api/agents/'+agent['id'],json={'kind':'remote','url':'https://example.com'}).status_code==200
    response=http.get('/api/preferences/chat')
    assert response.json()['agent_id'] is None
    assert 'agent_id' in response.headers['x-earthai-preferences-cleared']


def test_audit_time_range_queries_database_and_owner(client):
    http,user=client
    rows=[('old','2026-09-01T00:00:00+00:00'),('middle','2026-10-10T08:00:00+08:00'),('end','2026-10-11T00:00:00+00:00')]
    with store.connect() as db:
        db.executemany('INSERT INTO audit VALUES (?,?,?,?,?,?)',[(store.uid(),user['id'],action,'test','detail',stamp) for action,stamp in rows])
        db.execute('INSERT INTO audit VALUES (?,?,?,?,?,?)',(store.uid(),'other-user','invisible','test','secret','2026-10-10T00:00:00+00:00'))
    response=http.get('/api/audit',params={'start':'2026-10-10T00:00:00Z','end':'2026-10-11T00:00:00Z'})
    assert response.status_code==200
    assert [item['action'] for item in response.json()]==['end','middle']
    assert [item['action'] for item in http.get('/api/audit',params={'end':'2026-09-01T00:00:00Z'}).json()]==['old']
    assert http.get('/api/audit',params={'start':'2026-10-12T00:00:00Z','end':'2026-10-10T00:00:00Z'}).status_code==422
    assert http.get('/api/audit',params={'start':'invalid'}).status_code==422
    assert http.get('/api/audit',params={'start':'2026-10-10T00:00:00'}).status_code==422
    assert http.get('/api/audit',params={'limit':101}).status_code==422
