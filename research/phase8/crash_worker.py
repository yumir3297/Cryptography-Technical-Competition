"""Test-only independent process failure injection into SQLite acceptance."""
import json,sys
from .scene_authority import SceneAuthority
from .fixtures import prepare_approved

def main():
    path,profile,fixture,stage=sys.argv[1:]
    args=json.load(open(fixture,encoding='utf-8'))
    authority=SceneAuthority(path,profile)
    op=prepare_approved(authority,args['action'],args['task_id'],args['scene_key'])
    authority.accept(op,crash_at=stage)

if __name__=='__main__':main()
