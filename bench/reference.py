def longest_valid_parentheses(s):
    best=0; st=[-1]
    for i,c in enumerate(s):
        if c=='(': st.append(i)
        else:
            st.pop()
            if not st: st.append(i)
            else: best=max(best,i-st[-1])
    return best

def min_window(s,t):
    if not s or not t: return ""
    from collections import Counter
    need=Counter(t); miss=len(t); best=(float('inf'),0,0); l=0
    for r,c in enumerate(s):
        if need[c]>0: miss-=1
        need[c]-=1
        while miss==0:
            if r-l+1<best[0]: best=(r-l+1,l,r)
            need[s[l]]+=1
            if need[s[l]]>0: miss+=1
            l+=1
    return "" if best[0]==float('inf') else s[best[1]:best[2]+1]

def calculate(expr):
    s=expr.replace(" ","").replace("\t","")
    pos=[0]
    def parse_expr():
        v=parse_term()
        while pos[0]<len(s) and s[pos[0]] in '+-':
            op=s[pos[0]]; pos[0]+=1; r=parse_term()
            v = v+r if op=='+' else v-r
        return v
    def parse_term():
        v=parse_factor()
        while pos[0]<len(s) and s[pos[0]] in '*/':
            op=s[pos[0]]; pos[0]+=1; r=parse_factor()
            if op=='*': v=v*r
            else:
                q=abs(v)//abs(r); v = q if (v<0)==(r<0) else -q
        return v
    def parse_factor():
        if s[pos[0]]=='-': pos[0]+=1; return -parse_factor()
        if s[pos[0]]=='+': pos[0]+=1; return parse_factor()
        if s[pos[0]]=='(':
            pos[0]+=1; v=parse_expr(); pos[0]+=1; return v
        j=pos[0]
        while j<len(s) and s[j].isdigit(): j+=1
        v=int(s[pos[0]:j]); pos[0]=j; return v
    return parse_expr()

def word_break_all(s,words):
    if not s: return []
    ws=set(words); from functools import lru_cache
    @lru_cache(None)
    def go(i):
        if i==len(s): return [""]
        out=[]
        for j in range(i+1,len(s)+1):
            if s[i:j] in ws:
                for rest in go(j):
                    out.append(s[i:j] if rest=="" else s[i:j]+" "+rest)
        return out
    return sorted(go(0))

def topo_order(n,edges):
    import heapq
    adj={i:[] for i in range(n)}; indeg=[0]*n
    for u,v in edges:
        adj[u].append(v); indeg[v]+=1
    h=[i for i in range(n) if indeg[i]==0]; heapq.heapify(h); out=[]
    while h:
        u=heapq.heappop(h); out.append(u)
        for v in adj[u]:
            indeg[v]-=1
            if indeg[v]==0: heapq.heappush(h,v)
    return out if len(out)==n else None

def parse_qs(query):
    def dec(x):
        b=bytearray(); i=0
        while i<len(x):
            c=x[i]
            if c=='+': b.append(32); i+=1
            elif c=='%' and i+3<=len(x):
                try:
                    b.append(int(x[i+1:i+3],16)); i+=3
                except ValueError:
                    b.extend(c.encode()); i+=1
            else:
                b.extend(c.encode()); i+=1
        return b.decode('utf-8',errors='replace')
    out={}
    for seg in query.split('&'):
        if not seg: continue
        if '=' in seg: k,v=seg.split('=',1)
        else: k,v=seg,''
        k=dec(k); v=dec(v)
        if not k: continue
        out.setdefault(k,[]).append(v)
    return out
