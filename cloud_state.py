"""Restore the latest valid state artifact. Never expose tokens or topic names."""
import io
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, build_opener, HTTPRedirectHandler, urlopen
from urllib.error import HTTPError
from urllib.parse import urlparse
import zipfile

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def restore_zip(data, destination):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in ('state.json','STOPPED'):
            if name not in archive.namelist():
                continue
            if archive.getinfo(name).file_size>10_000_000:
                raise ValueError('State artifact too large')
            content=archive.read(name)
            if name=='state.json':
                obj=json.loads(content)
                if not isinstance(obj,dict) or not isinstance(obj.get('items'),dict) or not isinstance(obj.get('initialized'),bool):
                    raise ValueError('Invalid state artifact')
            (destination/name).write_bytes(content)

def main():
    repo=os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):
        raise ValueError('Invalid repository')
    headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'}
    endpoint=f'https://api.github.com/repos/{repo}/actions/artifacts?name=fancrew-state&per_page=100'
    with urlopen(Request(endpoint,headers=headers),timeout=30) as response:
        artifacts=json.load(response)['artifacts']
    artifacts=[a for a in artifacts if not a['expired'] and str(a.get('workflow_run',{}).get('id'))!=os.environ.get('GITHUB_RUN_ID')]
    if not artifacts:
        print('保存状態なし：初回の基準収集を開始します。')
        return
    latest=max(artifacts,key=lambda a:a['created_at'])
    artifact_id=int(latest['id'])
    request=Request(f'https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip',headers=headers)
    # GitHub redirects downloads to storage. Send no GitHub token to that host.
    try:
        with build_opener(NoRedirect()).open(request,timeout=30) as response:
            data=response.read()
    except HTTPError as e:
        if e.code!=302:
            raise
        location=e.headers['Location']
        if urlparse(location).scheme!='https':
            raise ValueError('Unsafe artifact redirect')
        with urlopen(location,timeout=30) as response:
            data=response.read()
    restore_zip(data,Path(__file__).resolve().parent)
    print('前回の監視状態を復元しました。')

if __name__=='__main__':
    try:
        main()
    except Exception as e:
        print('状態の復元失敗。重複通知を防ぐため実行を中止します。('+type(e).__name__+')',file=sys.stderr)
        raise SystemExit(1)
