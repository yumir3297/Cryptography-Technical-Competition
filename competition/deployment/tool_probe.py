"""Read-only simulator tool key preflight in the tool's own process.

Reports a derived public key only. Never executes an action or signs caller data.
"""
import json
from pathlib import Path
import sys
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from competition.support.final_fact import verify_certificate
from competition.support.wire import b64, raw, keyid, require
from competition.tools.common_tool import ToolGateway

def main(path):
    try:
        cfg=ToolGateway(path).config
        trust=verify_certificate(cfg['certificate'],raw(cfg['root_public'],32),'IND-DEMO-1')
        key=Ed25519PrivateKey.from_private_bytes(Path(cfg['tool_key_path']).read_bytes())
        pub=key.public_key().public_bytes_raw()
        require(b64(pub)==trust['value']['public_key'] and keyid(pub)==trust['value']['kid'],'TOOL_KEY')
        print(json.dumps({'profile':'IND-DEMO-1','kid':keyid(pub),'public_key':b64(pub)}),flush=True)
    except Exception as exc:
        print(json.dumps({'error':getattr(exc,'code','TOOL_PREFLIGHT_FAILED')}),flush=True)
        raise SystemExit(1)

if __name__=='__main__':main(sys.argv[1])
