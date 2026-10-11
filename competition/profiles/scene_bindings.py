"""Competition copy of original finite bindings; conditional V separation and E action scope.
Research Phase8 source remains byte-for-byte unchanged.
"""
from research.phase8.scene_authority import ACTION_FIELDS, ROLES, DEST, MAPPING, TEMPLATES
from research.reference_executor.wire import require, rec_ref

def bound_scene(self,c,action,task_id,scene_key,at=102):
    require(set(action)=={'scope','operation_id','principal','holder','holder_kid','executor','tool','tool_version','destination','payload'},'ACTION_FIELDS')
    require(action['scope']==self.scope and set(action['payload'])==ACTION_FIELDS[self.profile],'BINDING')
    p=action['payload'];pol=self.current(c,'POLICY',self.scope_key())['record']['value']
    task=self.current(c,'TASK',self.scope_key()+[task_id])['record']['value']
    s=self._scene_current(c,scene_key);sr=s['record']['value'];ev=self.current(c,'EVIDENCE',scene_key)['record']
    identity_key=(self.scope_key()+[p['unit_id']] if self.profile=='IND-DEMO-1'
                  else self.scope_key()+[p['synthetic_patient_id'],p['encounter_id']])
    ident=self.current(c,'IDENTITY',identity_key)
    require(rec_ref(ident['record'])==sr['unit_ref' if self.profile=='IND-DEMO-1' else 'encounter_ref'],'IDENTITY_BINDING')
    if self.profile=='IND-DEMO-1':
        package=self.current(c,'PACKAGE',self.scope_key())
        require(pol['decision_package_ref']==package['ref'],'PACKAGE_BINDING')
        pkg=package['record']['value']
        require(pkg['package_id']=='ind-fixed-package-1' and pkg['detector']=='SYNTHETIC-LABEL-1' and
                pkg['preprocessing']=='IDENTITY-1' and pkg['output_schema']=='IND-LABEL-V1' and
                pkg['mapper']=='IND-ROUTE-V1' and pkg['label_routes']=={'normal':'RELEASE','defect':'QUARANTINE','uncertain':'INSPECT'},'PACKAGE_BINDING')
    self._credential(c,'E','SOURCE','SOURCE',action)
    self.verify_evidence(c,ev,at)
    ed=ev['value']['data']
    require(sr['state']=='READY' and sr['evidence_ref']==rec_ref(ev),'STALE')
    require(action['holder']==task['holder']==self.actors['H'].name and action['holder_kid']==task['holder_kid']==self.actors['H'].kid,'WRONG_HOLDER')
    require(action['principal']==task['principal'] and action['executor']==task['executor']==pol['executor']==self.actors['X'].name,'BINDING')
    require(action['tool']==pol['tool']==task['tool'] and action['tool_version']==pol['tool_version']==task['tool_version']=='1','BINDING')
    require(task['policy_ref']==self.current(c,'POLICY',self.scope_key())['ref'],'STALE')
    require(int(task['iat'])<=at<int(task['exp']) and int(pol['iat'])<=at<int(pol['exp']),'EXPIRED')
    require(pol['gateway_kid']==self.actors['G'].kid and pol['executor_kid']==self.actors['X'].kid,'KEY_BINDING')
    require(pol['gateway']==self.actors['G'].name and pol['source']==self.actors['E'].name,'BINDING')
    for alias in ('H','G','X','U')+ (('V',) if (self.profile=='MED-DEMO-1' or (self.profile=='IND-DEMO-1' and action['payload'].get('route')=='INSPECT')) else ()):
        role=ROLES[self.profile][alias]
        # All required subjects are distinct; never compare only kid.
        purpose={'H':'CommitProof','G':'Permit','X':'Acceptance','U':'Authorization','V':'Review'}[alias]
        self._credential(c,alias,role,purpose,action)
        self._read_permission(c,alias,action,pol)
    require(self.actors['U'].name not in (self.actors['G'].name,self.actors['X'].name),'SUBJECT_SEPARATION')
    if self.profile=='MED-DEMO-1' or p.get('route')=='INSPECT':
        require(self.actors['V'].name not in (self.actors['U'].name,self.actors['G'].name,self.actors['X'].name),'SUBJECT_SEPARATION')
    if self.profile=='IND-DEMO-1':
        require(p['line_id']==task['line_id']==pol['line_id']==ed['line_id']=='demo-line-a' and
                p['station_id']==task['station_id']==pol['station_id']==ed['station_id']=='demo-check-1','BINDING')
        require([p['line_id'],p['unit_id']]==scene_key[-2:] and p['unit_id']==ed['unit_id'] and p['batch_id']==ed['batch_id'],'BINDING')
        require(p['inspection_cycle']==ed['inspection_cycle']==sr['inspection_cycle'] and p['phase']==ed['phase']==sr['phase'],'BINDING')
        require(p['route']==MAPPING[ed['label']] and p['route'] in task['allowed_routes'] and
                action['destination']==DEST[p['route']],'CLAIM_FALSE')
        allowed={'unit_ref':sr['unit_ref'],'unit_id':p['unit_id'],'batch_id':p['batch_id'],
                 'inspection_cycle':p['inspection_cycle'],'phase':p['phase']}
        require(allowed in task['allowed_units'],'BINDING')
        required=['QUALITY_REVIEW'] if p['route']=='INSPECT' else []
    else:
        require(p['synthetic_patient_id']==task['synthetic_patient_id']==ed['synthetic_patient_id'] and
                p['encounter_id']==task['encounter_id']==ed['encounter_id'] and p['order_group_id']==task['order_group_id']==sr['order_group_id'],'BINDING')
        require(p['record_ref']==rec_ref(ev) and task['encounter_ref']==ed['encounter_ref']==sr['encounter_ref'],'BINDING')
        require(p['phase']==task['phase']=='SUBMIT' and p['template_id']==TEMPLATES[ed['template_label']] and
                p['template_id'] in task['allowed_templates'],'CLAIM_FALSE')
        require(action['destination']==pol['destination']==task['destination']==p['destination_system']=='med-demo-ledger','BINDING')
        required=['CLINICAL_REVIEW']
    roles=[(a,ROLES[self.profile][a]) for a in ('H','E','G','X','U')]
    if required:roles.append(('V',ROLES[self.profile]['V']))
    # R2 requires READER roles for anyone who accesses patient/unit data.
    roles.extend((a,'READER') for a in ('H','G','X','U')+ (('V',) if required else ()))
    return pol,task,ev,s,required,self._deps(c,action,task_id,scene_key,roles)
