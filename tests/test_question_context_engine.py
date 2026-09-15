"""Saved questions survive engine pickup and replies keep their exact scope."""
from tests.test_usage_checkpoint_engine import cockpit
from steward_cockpit import steward_engine as engine_mod


def finish(engine,text):
    engine.turn_text=text
    engine._handle({'type':'result','total_cost_usd':0.0,'duration_ms':1,'usage':{}},engine.proc)


def test_question_saved_at_result_survives_restart_with_full_context(cockpit,monkeypatch):
    monkeypatch.setattr(cockpit,'_attention',lambda:{'state':'quiet'})
    text='The shared method changes every block.\nI recommend solving it once.\nShould we use one shared method?'
    finish(cockpit,text)
    saved=cockpit.state()['question_context']
    assert saved['question']=='Should we use one shared method?'
    assert saved['context']==text
    assert saved['recommendation']=='I recommend solving it once.'
    restarted=engine_mod.Engine(cockpit.dir,fake=True)
    monkeypatch.setattr(restarted,'_attention',lambda:{'state':'quiet'})
    assert restarted.state()['question_context']==saved


def test_answer_context_is_saved_and_delivered_without_minting_acceptance(cockpit,monkeypatch):
    monkeypatch.setattr(cockpit,'_attention',lambda:{'state':'quiet'})
    finish(cockpit,'This affects the plan.\nI recommend one shared method.\nUse one shared method?')
    saved=cockpit.state()['question_context'];sent=[]
    monkeypatch.setattr(cockpit,'_send_locked',lambda text:(sent.append(text),True)[1])
    assert cockpit.say('Yes',question_id=saved['id'])['ok']
    assert len(sent)==1 and saved['question'] in sent[0]
    assert 'not automatic acceptance' in sent[0]
    assert cockpit.question_history[-1]['answer']=='Yes'
    assert cockpit.question_history[-1]['question']['id']==saved['id']
    assert cockpit.state()['question_context'] is None
    assert not cockpit.say('Yes',question_id=saved['id'])['ok']
    assert len(sent)==1,'A stale reply must never reach the model'


def test_managed_nonreview_decision_is_bound_to_work_and_does_not_revive_after_change(cockpit,monkeypatch):
    attention={'state':'quiet','managed_refinement':True,'pending_request':None,'work_digest':'work-1'}
    monkeypatch.setattr(cockpit,'_attention',lambda:attention)
    finish(cockpit,'This affects both blocks.\nI recommend a shared solution.\nUse that approach?')
    assert cockpit.state()['question_context']['question']=='Use that approach?'
    assert cockpit.state()['light']=='orange'
    attention['work_digest']='work-2'
    assert cockpit.state()['question_context'] is None
    assert cockpit.state()['open_question']==''
    assert cockpit.state()['light']=='quiet'


def test_review_context_expires_when_its_exact_request_is_resolved(cockpit,monkeypatch):
    request={'id':'review-1','step_id':'lecture','presentation_id':'p1','purpose':'Review this lecture',
             'source_message':'The source explanation is preserved.'}
    attention={'state':'needs_you','managed_refinement':True,'pending_request':request}
    monkeypatch.setattr(cockpit,'_attention',lambda:attention)
    finish(cockpit,'This is the revised lecture.\nI recommend this version.\nDoes this version look good?')
    saved=cockpit.state()['question_context']
    assert saved['authorization_scope']['presentation_id']=='p1'
    attention.update(state='quiet',pending_request=None)
    assert cockpit.state()['question_context'] is None
    assert not cockpit.say('Yes',question_id=saved['id'])['ok']

