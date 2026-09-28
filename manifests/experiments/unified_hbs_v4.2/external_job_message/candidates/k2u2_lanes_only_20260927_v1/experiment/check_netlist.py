"""Compare EDIF structure, ignoring only names of nets/lanes and item order."""
import hashlib,json,re,sys
from pathlib import Path

def fingerprint(path):
    text=path.read_text()
    for i in range(2):
        text=text.replace(f'(rename lanes_{i}__lane "lanes[{i}].lane")',f'lane{i}').replace(f'lanes_{i}__lane',f'lane{i}')
    tokens=iter(re.finditer(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+',text))
    counts={'net':0,'instance':0,'cell':0}
    def atom(t):return ('a',t)
    def digest(items):
        return hashlib.sha256(json.dumps(items,separators=(',',':')).encode()).hexdigest()
    def node():
        items=[]
        for m in tokens:
            t=m[0]
            if t==')':break
            items.append(node() if t=='(' else atom(t))
        kind=items[0][1]
        if kind in ('netRef','netref'):raise AssertionError('net names referenced')
        if kind in counts:counts[kind]+=1
        if kind=='timeStamp':items=items[:1]
        if kind=='net':items=items[:1]+items[2:]
        if kind in ('contents','joined'):items=items[:1]+sorted(items[1:])
        return ('n',digest(items))
    assert next(tokens)[0]=='('
    value=node()
    assert next(tokens,None) is None
    return dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),structure_sha256=value[1],counts=counts)

a,b=map(Path,sys.argv[1:3]);x,y=fingerprint(a),fingerprint(b)
result=dict(passed=x['structure_sha256']==y['structure_sha256'],baseline=x,candidate=y,
 normalization=['timestamp','two physical lane instance names','internal net names','contents and joined order'],
 scope='all EDIF cell definitions, ports, instances, primitive properties, net pin connectivity')
print(json.dumps(result,indent=2))
assert result['passed']
