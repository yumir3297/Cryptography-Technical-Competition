"""Synthetic, isolated records matching the listed official IND/MED field names.
Not production evidence, not real industrial commands or clinical orders.
"""
from pathlib import Path
from research.reference_executor.wire import sid, b64, rec_ref, action_hash, sortset
from .scene_authority import SceneAuthority, _rec, DEST, TEMPLATES, MAPPING


def build_scene(path,profile,label=None,authority_class=SceneAuthority,*,controller=None,actors=None):
    # Optional provisioned principals: defaults preserve the original reference fixture.
    # The independent-role pilot injects fresh keys instead of hard-coded test seeds.
    opts={}
    if controller is not None:opts['controller']=controller
    if actors is not None:opts['actors']=actors
    a=authority_class(path,profile,**opts)
    if hasattr(a,"enroll_actor"):
        for alias in a.actors:a.enroll_actor(alias)
    for key in a.actors:
        # A READER is an independent C-granted role, not implied by HOLDER/doctor.
        roles=[next(iter(a.actors[key].roles))]
        if key in ('H','G','X','U','V'):roles.append('READER')
        a.grant(key,roles)
    actors=a.actors;scope=a.scope;now='100';exp='1900'
    readers=sortset([x.name for x in actors.values()])
    if profile=='IND-DEMO-1':
        label=label or 'DEMO_NORMAL';route=MAPPING[label]
        pkg=_rec(profile,'IND_PACKAGE',scope,{'package_id':'ind-fixed-package-1','package_revision':'1',
            'detector':'SYNTHETIC-LABEL-1','preprocessing':'IDENTITY-1',
            'output_schema':'IND-LABEL-V1','mapper':'IND-ROUTE-V1',
            'label_routes':{'normal':'RELEASE','defect':'QUARANTINE','uncertain':'INSPECT'},'iat':'1','exp':exp})
        # Package nomenclature checked by scene rules; value may differ from full official consts.
        pkg_ref=rec_ref(pkg)
        a.publish('PACKAGE',a.scope_key(),pkg)
        pv={'profile':profile,'policy_revision':'1','schema_version':'ind-payload-v1','verifier_version':'ind-fixed-v1',
            'gateway':actors['G'].name,'gateway_kid':actors['G'].kid,'executor':actors['X'].name,
            'executor_kid':actors['X'].kid,'source':actors['E'].name,'readers':readers,'tool':'line-sort-sim',
            'tool_version':'1','controller':'fixture-controller','line_id':'demo-line-a','station_id':'demo-check-1',
            'route_destinations':{'release':DEST['RELEASE'],'quarantine':DEST['QUARANTINE'],'inspect':DEST['INSPECT']},
            'decision_package_ref':pkg_ref,'history_mode':'DISABLED','max_cycles':'2','evidence_ttl_seconds':'300',
            'task_ttl_seconds':'900','behavior_count_cap':'32','capacity_per_destination':'8','iat':'1','exp':exp}
        a.publish('POLICY',a.scope_key(),_rec(profile,'POLICY',scope,pv))
        identity=_rec(profile,'IND_UNIT',scope,{'unit_id':'unit-a','batch_id':'batch-a',
               'line_id':'demo-line-a','station_id':'demo-check-1','synthetic':True,'iat':'1','exp':exp})
        a.publish('IDENTITY',a.scope_key()+['unit-a'],identity)
        key=a.scope_key()+['demo-line-a','unit-a'];idref=rec_ref(identity)
        initial={'unit_ref':idref,'inspection_cycle':'1','phase':'INITIAL','state':'READY',
                 'evidence_ref':'','operation_id':'','predecessor_operation_id':'','predecessor_commit_ref':''}
        a.init_scene(key,initial)
        evidence_data={'evidence_id':sid(40),'evidence_revision':'1','unit_ref':idref,'unit_id':'unit-a',
            'batch_id':'batch-a','line_id':'demo-line-a','station_id':'demo-check-1',
            'inspection_cycle':'1','phase':'INITIAL','sampled_at':'95','known_at':'96',
            'quality_flag':'VALID','label':label}
        ev=a.sign_evidence(evidence_data)
        ev_ref=a.import_evidence(ev,key)
        task_id=sid(41)
        tv={'task_id':task_id,'task_revision':'1','principal':'principal','holder':actors['H'].name,
            'holder_kid':actors['H'].kid,'executor':actors['X'].name,
            'policy_ref':a._read_row('POLICY',a.scope_key())['ref'],'line_id':'demo-line-a',
            'station_id':'demo-check-1','allowed_units':[{'unit_ref':idref,'unit_id':'unit-a',
                 'batch_id':'batch-a','inspection_cycle':'1','phase':'INITIAL'}],
            'allowed_routes':['INSPECT','QUARANTINE','RELEASE'], 'tool':'line-sort-sim','tool_version':'1',
            'route_destinations':pv['route_destinations'],'max_inflight':'1','iat':'1','exp':'500'}
        a.publish('TASK',a.scope_key()+[task_id],_rec(profile,'IND_TASK',scope,tv))
        payload={'line_id':'demo-line-a','station_id':'demo-check-1','unit_id':'unit-a',
                 'batch_id':'batch-a','inspection_cycle':'1','phase':'INITIAL','route':route}
        action={'scope':scope,'operation_id':sid(42),'principal':'principal','holder':actors['H'].name,
                'holder_kid':actors['H'].kid,'executor':actors['X'].name,'tool':'line-sort-sim',
                'tool_version':'1','destination':DEST[route],'payload':payload}
    else:
        label=label or 'DEMO_A'
        pv={'profile':profile,'policy_revision':'1','schema_version':'med-payload-v1','verifier_version':'med-fixed-v1',
            'gateway':actors['G'].name,'gateway_kid':actors['G'].kid,'executor':actors['X'].name,
            'executor_kid':actors['X'].kid,'source':actors['E'].name,'readers':readers,
            'tool':'med-order-sim','tool_version':'1','controller':'fixture-controller','destination':'med-demo-ledger',
            'allowed_templates':['DEMO-ORDER-A','DEMO-ORDER-B'],
            'template_mapping':{'demo_a':'DEMO-ORDER-A','demo_b':'DEMO-ORDER-B'},
            'history_mode':'DISABLED','required_review':'CLINICAL_REVIEW','evidence_ttl_seconds':'300',
            'task_ttl_seconds':'900','behavior_count_cap':'32','destination_capacity':'8',
            'max_groups_per_encounter':'1','iat':'1','exp':exp}
        a.publish('POLICY',a.scope_key(),_rec(profile,'POLICY',scope,pv))
        identity=_rec(profile,'MED_ENCOUNTER',scope,{'synthetic_patient_id':'patient-a',
                    'encounter_id':'encounter-a','synthetic':True,'iat':'1','exp':exp})
        a.publish('IDENTITY',a.scope_key()+['patient-a','encounter-a'],identity)
        key=a.scope_key()+['patient-a','encounter-a'];idref=rec_ref(identity)
        initial={'encounter_ref':idref,'order_group_id':sid(61),'phase':'SUBMIT','state':'READY',
                 'evidence_ref':'','operation_id':''}
        a.init_scene(key,initial)
        evidence_data={'evidence_id':sid(62),'evidence_revision':'1','record_id':'record-a',
                       'record_revision':'1','encounter_ref':idref,'synthetic_patient_id':'patient-a',
                       'encounter_id':'encounter-a','record_status':'AVAILABLE','completeness':'COMPLETE',
                       'event_at':'95','known_at':'97','template_label':label}
        ev=a.sign_evidence(evidence_data)
        ev_ref=a.import_evidence(ev,key)
        task_id=sid(63)
        tv={'task_id':task_id,'task_revision':'1','principal':'principal','holder':actors['H'].name,
            'holder_kid':actors['H'].kid,'executor':actors['X'].name,
            'policy_ref':a._read_row('POLICY',a.scope_key())['ref'], 'encounter_ref':idref,
            'synthetic_patient_id':'patient-a','encounter_id':'encounter-a','order_group_id':sid(61),
            'phase':'SUBMIT','allowed_templates':['DEMO-ORDER-A','DEMO-ORDER-B'],
            'tool':'med-order-sim','tool_version':'1','destination':'med-demo-ledger',
            'max_inflight':'1','iat':'1','exp':'500'}
        a.publish('TASK',a.scope_key()+[task_id],_rec(profile,'MED_TASK',scope,tv))
        payload={'synthetic_patient_id':'patient-a','encounter_id':'encounter-a','order_group_id':sid(61),
                 'phase':'SUBMIT','template_id':TEMPLATES[label],'record_ref':ev_ref,
                 'destination_system':'med-demo-ledger'}
        action={'scope':scope,'operation_id':sid(64),'principal':'principal',
                'holder':actors['H'].name,'holder_kid':actors['H'].kid,
                'executor':actors['X'].name,'tool':'med-order-sim','tool_version':'1',
                'destination':'med-demo-ledger','payload':payload}
    a.init_behavior(action['principal'])
    return a,action,task_id,key,ev


def prepare_approved(a,action,task_id,key):
    op=a.prepare(action,task_id,key)
    if op['required']:a.review(op)
    a.authorize(op);a.issue(op);a.challenge(op);a.proof(op)
    return op
